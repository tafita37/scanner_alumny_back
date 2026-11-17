"""
Tests du service du questionnaire sans base de données ni LLM : alias des parties dans les deux sens,
masquage des questions précédentes, questions construites à partir du résultat du graphe.
Lancement : python manage.py test companies.tests.test_questionnaire_service
"""
import json

from django.test import SimpleTestCase

from companies.metier.question import Question, StatutQuestion
from companies.metier.questionnaire import Questionnaire
from companies.services.anonymization import PseudonymMapping, deanonymize
from companies.services.audit_context import PartyAliases
from companies.services.previous_questions import TextMasker
from companies.services.questionnaire import build_questions


def make_aliases() -> PartyAliases:
    aliases = PartyAliases('123456789', 'Bâtir Ouest SARL')
    aliases.alias_for('Bâtir Ouest SARL', '12345678900012')
    aliases.alias_for('Jean Dupont')
    aliases.alias_for('SCI Les Tilleuls')
    return aliases


class PartyAliasesTests(SimpleTestCase):

    def test_restore_names(self):
        aliases = make_aliases()
        result = aliases.restore({
            'analyse': 'PARTIE_1 doit 45 000 € à ENTREPRISE_AUDITEE.',
            'questions': [{'label': 'PARTIE_2 a-t-elle payé ?', 'document_ids': [12]}],
        })
        self.assertEqual(result['analyse'], 'Jean Dupont doit 45 000 € à Bâtir Ouest SARL.')
        self.assertEqual(result['questions'][0], {'label': 'SCI Les Tilleuls a-t-elle payé ?', 'document_ids': [12]})
        self.assertEqual(aliases.restore('PARTIE_9 et PARTIE_10'), 'PARTIE_9 et PARTIE_10')  # alias inconnus
        # Le LLM écrit parfois l'alias avec une espace
        self.assertEqual(aliases.restore('Part du client « PARTIE 1 » ?'), 'Part du client « Jean Dupont » ?')

    def test_mask_names(self):
        aliases = make_aliases()
        self.assertEqual(
            aliases.mask('Le client JEAN  dupont paie à 90 jours ; la sci les tilleuls aussi.'),
            'Le client PARTIE_1 paie à 90 jours ; la PARTIE_2 aussi.',
        )
        self.assertEqual(aliases.mask('Bâtir Ouest SARL facture'), 'ENTREPRISE_AUDITEE facture')
        # Un nom n'est remplacé qu'en mot entier
        self.assertEqual(aliases.mask('Jean Dupontel'), 'Jean Dupontel')

    def test_restore_then_mask_gives_back_aliases(self):
        aliases = make_aliases()
        text = 'Relancer PARTIE_1 et PARTIE_2 pour ENTREPRISE_AUDITEE.'
        self.assertEqual(aliases.mask(aliases.restore(text)), text)


class TextMaskerTests(SimpleTestCase):

    def test_previous_question_is_masked(self):
        mapping = PseudonymMapping()
        masker = TextMasker(mapping, make_aliases())
        masked = masker.mask('Le chantier de Jean Dupont suivi par M. Pierre Martin est-il réceptionné ?')
        self.assertIn('PARTIE_1', masked)
        self.assertNotIn('Martin', masked)
        self.assertIn('<PERSON_', masked)
        self.assertIn('Pierre Martin', deanonymize(masked, mapping))

    def test_answers(self):
        masker = TextMasker(PseudonymMapping(), make_aliases())
        texte = Question(answer_type='texte')
        self.assertEqual(masker.answer(texte, json.dumps('Jean Dupont paie en retard')), 'PARTIE_1 paie en retard')
        self.assertEqual(masker.answer(Question(answer_type='montant'), '340000'), 340000)
        self.assertIs(masker.answer(Question(answer_type='oui_non'), 'true'), True)
        self.assertIsNone(masker.answer(texte, None))
        self.assertEqual(masker.mask('   '), '   ')


class BuildQuestionsTests(SimpleTestCase):

    def test_questions_from_result(self):
        questionnaire = Questionnaire(round_number=2)
        built = build_questions(questionnaire, {
            'analyse': 'Analyse.',
            'questions': [
                {'label': 'Délai de paiement ?', 'rationale': 'Retard.', 'answer_type': 'choix',
                 'choices': ['30 jours', '60 jours'], 'unit': None, 'document_ids': [12, 70],
                 'suggested_answer': '60 jours', 'suggested_answer_source': 'Facture 70, page 1'},
                {'label': 'Acompte perçu ?', 'rationale': 'Trésorerie.', 'answer_type': 'oui_non',
                 'choices': None, 'unit': None, 'document_ids': [],
                 'suggested_answer': False, 'suggested_answer_source': 'Devis 12, page 3'},
            ],
        })
        (first, first_documents), (second, second_documents) = built
        self.assertEqual((first.display_order, second.display_order), (1, 2))
        self.assertIs(first.questionnaire, questionnaire)
        self.assertEqual(json.loads(first.choices), ['30 jours', '60 jours'])
        self.assertEqual(json.loads(first.suggested_answer), '60 jours')
        self.assertEqual(first_documents, [12, 70])
        self.assertIsNone(second.choices)
        self.assertEqual(second.suggested_answer, 'false')
        self.assertEqual(second_documents, [])
        self.assertEqual(second.status, StatutQuestion.EN_ATTENTE)
        self.assertIsNone(second.answer)
