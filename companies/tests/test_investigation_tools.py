"""
Tests des tools d'enquête de l'agent du questionnaire, sur des pages écrites à la main : ni base
de données ni LLM (l'anonymisation, elle, tourne réellement : Presidio + spaCy).
Lancement : python manage.py test companies.tests.test_investigation_tools
"""
from django.test import SimpleTestCase

from companies.services.anonymization import PseudonymMapping
from companies.services.investigation_tools import (
    MAX_RESULTS,
    SNIPPET_RADIUS,
    AuditTexts,
    format_ranges,
)

FILLER = 'Le présent document est établi selon les conditions habituelles de l\'entreprise. ' * 6

DEVIS = {
    'type_document': 'devis',
    'pages': {
        1: 'Devis n° 2026-014. Délai d\'exécution : 14 mois.\n\n' + FILLER,
        3: FILLER + 'Les prix sont fermes et non révisables pour toute la durée du chantier. ' + FILLER,
    },
}
FACTURE = {
    'type_document': 'facture',
    'pages': {
        1: 'Facture n° 88. ' + FILLER + 'Pénalités de retard : trois fois le taux d\'intérêt légal.\n'
           'Livraison franco de port à partir de 500 € HT. ' + FILLER,
    },
}
SANS_TEXTE = {'type_document': 'devis', 'pages': None}


def make_texts(documents=None) -> AuditTexts:
    return AuditTexts(documents or {12: DEVIS, 70: FACTURE, 73: SANS_TEXTE}, PseudonymMapping())


class SearchTests(SimpleTestCase):

    def test_ignores_case_and_accents(self):
        result = make_texts().search(['REVISABLE'])
        self.assertEqual(result['nombre_total'], 1)
        found = result['resultats'][0]
        self.assertEqual((found['document_id'], found['page'], found['type_document']), (12, 3, 'devis'))
        self.assertIn('non révisables', found['extrait'])

    def test_term_starts_a_word_but_may_not_end_it(self):
        texts = make_texts()
        self.assertEqual(texts.search(['révis'])['nombre_total'], 1)
        # « port » ne doit pas trouver « rapport ».
        texts = make_texts({1: {'type_document': 'devis', 'pages': {1: 'Voir le rapport annuel.'}}})
        self.assertEqual(texts.search(['port'])['nombre_total'], 0)

    def test_term_split_across_lines(self):
        texts = make_texts({1: {'type_document': 'devis', 'pages': {1: 'Clause de révision\nde  prix : indice BT01.'}}})
        self.assertEqual(texts.search(['révision de prix'])['nombre_total'], 1)

    def test_close_matches_are_merged(self):
        result = make_texts().search(['pénalités', 'franco'])
        self.assertEqual(result['nombre_total'], 1)
        self.assertEqual(result['resultats'][0]['termes_trouves'], ['pénalités', 'franco'])

    def test_snippet_is_cut_between_words(self):
        snippet = make_texts().search(['révisables'])['resultats'][0]['extrait']
        self.assertTrue(snippet.startswith('…') and snippet.endswith('…'))
        self.assertLessEqual(len(snippet), 2 * SNIPPET_RADIUS + len('révisables') + 2)
        # Pas de mot coupé : le texte après « … » commence un mot du FILLER.
        first_word = snippet[1:].split()[0]
        self.assertIn(first_word, FILLER.split() + ['Les'])

    def test_results_are_capped_with_real_total(self):
        page = (' '.join(['avenant'] + ['mot'] * 120) + ' ') * 15  # 15 occurrences éloignées
        result = make_texts({1: {'type_document': 'devis', 'pages': {1: page}}}).search(['avenant'])
        self.assertEqual(result['nombre_total'], 15)
        self.assertEqual(len(result['resultats']), MAX_RESULTS)

    def test_no_result_lists_documents_without_text(self):
        result = make_texts().search(['retenue de garantie'])
        self.assertEqual(result, {'resultats': [], 'nombre_total': 0, 'documents_sans_texte': [73]})

    def test_invalid_terms(self):
        texts = make_texts()
        self.assertIn('erreur', texts.search([]))
        self.assertIn('erreur', texts.search(['  ', '']))
        self.assertIn('erreur', texts.search(['a', 'b', 'c', 'd', 'e', 'f']))


class AnonymizationTests(SimpleTestCase):

    def test_personal_data_is_replaced_and_token_can_be_searched(self):
        documents = {
            1: {'type_document': 'devis', 'pages': {
                1: 'Chantier suivi par M. Jean Dupont, conducteur de travaux. Retenue de garantie de 5 %.',
            }},
            2: {'type_document': 'facture', 'pages': {
                1: 'Facture adressée à M. Jean Dupont. Paiement à 60 jours.',
            }},
        }
        texts = make_texts(documents)
        found = texts.search(['retenue de garantie'])['resultats'][0]
        self.assertNotIn('Dupont', found['extrait'])
        token = next(word for word in found['extrait'].replace(',', ' ').split() if word.startswith('<PERSON_'))
        # Le jeton est cherchable, et désigne la même personne dans l'autre document.
        result = texts.search([token])
        self.assertEqual({r['document_id'] for r in result['resultats']}, {1, 2})
        self.assertTrue(all(token in r['extrait'] for r in result['resultats']))


class ReadTests(SimpleTestCase):

    def test_reads_requested_pages(self):
        result = make_texts().read(12, [3, 1])
        self.assertEqual([page['page'] for page in result['pages']], [1, 3])
        self.assertIn('non révisables', result['pages'][1]['texte'])
        self.assertNotIn('pages_absentes', result)

    def test_missing_pages_are_reported_with_available_ones(self):
        result = make_texts().read(12, [3, 5])
        self.assertEqual([page['page'] for page in result['pages']], [3])
        self.assertEqual(result['pages_absentes'], [5])
        self.assertEqual(result['pages_disponibles'], '1, 3')
        self.assertIn('erreur', make_texts().read(12, [5]))

    def test_errors(self):
        texts = make_texts()
        self.assertIn("n'appartient pas", texts.read(99, [1])['erreur'])
        self.assertIn('non disponible', texts.read(73, [1])['erreur'])
        self.assertIn('erreur', texts.read(12, []))
        self.assertIn('erreur', texts.read(12, [1, 2, 3, 4]))

    def test_format_ranges(self):
        self.assertEqual(format_ranges([13, 1, 2, 3, 4, 12, 20]), '1 à 4, 12 à 13, 20')
