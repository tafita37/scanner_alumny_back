"""
Tests du rapport PDF sans base de données ni LLM : mise en forme pour le client, rendu WeasyPrint
(10 à 12 pages, lien Calendly cliquable, aucune mention interne), format de l'API et routes.
Lancement : python manage.py test companies.tests.test_report
"""
import io
import json
from datetime import date

import pymupdf
import pypdfium2
from django.test import SimpleTestCase
from django.urls import resolve, reverse

from companies.controllers import report_controller
from companies.controllers.report_controller import report_payload
from companies.services.report_pdf import (
    build_report_context,
    client_text,
    fmt_answer,
    fmt_number,
    fmt_value,
    render_report_pdf,
)
from rapport.validation import ACTIONS_PAR_LEVIER, MOTS_MAX, NB_LEVIERS, PARAGRAPHES_SYNTHESE, POINTS_CLES
from structuration.moteurs import calculer_cockpit

CALENDLY = 'https://calendly.com/alumny-test/bilan-strategique'
COMPANY = {
    'name': 'BATI DURAN SARL', 'siren': '123456789', 'siret': '12345678900012', 'naf': '43.99C',
    'legal_form': 'SARL unipersonnelle', 'city': 'Angoulême', 'creation_date': date(2012, 3, 1), 'sector': 'BTP',
}
PUBLISHED = {'annee': 2025, 'chiffre_affaires': 1500000.0, 'resultat_net': 50000.0, 'effectif': 12}
INDICATORS = {
    'documents_pris_en_compte': 6,
    'documents_a_verifier': 0,
    'effectif': {'valeur': 12, 'source': 'comptes_annuels'},
    'documents_commerciaux': {
        'taux_horaire_main_oeuvre': 42.0,
        'heures_main_oeuvre': 120,
        'conditions_de_paiement': {'acompte_pourcentage_moyen': 30.0, 'delai_reglement_jours_moyen': 75.0},
    },
    'comptes_annuels': {
        'date_cloture': '2025-12-31', 'duree_exercice_mois': 12,
        'masse_salariale_annuelle': 704000.0, 'masse_salariale_mensuelle': 58666.67,
    },
}
ANSWERS = {
    'heures_facturables_mensuelles': {'statut': 'repondue', 'valeur': 1400, 'tour': 1},
    'volume_heures_mensuel': {'statut': 'ignoree', 'valeur': None, 'tour': 1},
}


SECTEURS = ('BTP', 'SERVICES', 'INDUSTRIE')


def cockpit(secteur: str = 'BTP') -> dict:
    return calculer_cockpit(secteur, INDICATORS, ANSWERS, {'tours_ok': 2, 'dernier_tour_vide': True})


def question(label, answer_type, answer, status='repondue', unit=None, variable=None) -> dict:
    return {'label': label, 'answer_type': answer_type, 'unit': unit, 'status': status,
            'answer': json.dumps(answer) if answer is not None else None, 'variable': variable}


QUESTIONS = [
    question("Combien d'heures facturables réelles par mois ?", 'nombre', 1400, unit='h',
             variable='heures_facturables_mensuelles'),
    question("Quel volume d'heures mensuel ?", 'nombre', None, status='ignoree', variable='volume_heures_mensuel'),
    question('Les avenants sont-ils signés avant les travaux supplémentaires ?', 'oui_non', False),
] + [question(f'Question complémentaire numéro {n} sur les conditions de paiement de vos clients ?', 'texte',
              'Le client paie souvent avec trois semaines de retard.') for n in range(12)]

PHRASE = ('Votre entreprise dégage un résultat positif, mais une partie de la valeur produite sur les chantiers '
          'ne se retrouve pas dans la facturation : heures non facturées, travaux supplémentaires sans avenant et '
          'délais de règlement de 75 jours pèsent sur la trésorerie.')


def mots(genre: str, maximum: bool) -> str:
    """Texte d'exemple ; `maximum` : exactement MOTS_MAX[genre] mots (pire cas accepté par la validation)."""
    if not maximum:
        return ' '.join(PHRASE.split()[:min(MOTS_MAX[genre], 30)])
    return ' '.join((PHRASE.split() * 10)[:MOTS_MAX[genre]])


def content(maximum: bool = False, secteur: str = 'BTP') -> dict:
    """Textes rédigés ; `maximum` : longueurs et nombres d'éléments maximaux autorisés par la validation."""
    return {
        'synthese_executive': [mots('paragraphe de la synthèse', maximum)] * (PARAGRAPHES_SYNTHESE[1] if maximum else 3),
        'points_cles': [mots('point clé', maximum)] * (POINTS_CLES[1] if maximum else 3),
        'commentaire_perte': mots('commentaire de la perte', maximum),
        'commentaires_indicateurs': [{'cle': i['cle'], 'commentaire': mots("commentaire d'indicateur", maximum)}
                                     for i in cockpit(secteur)['indicateurs']],
        'leviers': [{
            'titre': mots('titre de levier', maximum),
            'constat': mots('constat de levier', maximum),
            'actions': [mots('action', maximum)] * (ACTIONS_PAR_LEVIER[1] if maximum else 2),
            'gain_attendu': mots('gain attendu', maximum),
            'indicateur_suivi': mots('indicateur de suivi', maximum),
        } for _ in range(NB_LEVIERS)],
        'message_conclusion': mots('message de conclusion', maximum),
    }


ARGS = {
    'company': COMPANY, 'published': PUBLISHED, 'indicators': INDICATORS, 'cockpit': cockpit(), 'content': content(),
    'questions': QUESTIONS, 'calendly_url': CALENDLY, 'audit_date': date(2026, 11, 2), 'generated_on': date(2026, 11, 19),
}


def context(maximum: bool = False, secteur: str = 'BTP') -> dict:
    return build_report_context(
        company=COMPANY, published=PUBLISHED, indicators=INDICATORS, cockpit=cockpit(secteur),
        content=content(maximum, secteur),
        questions=QUESTIONS, calendly_url=CALENDLY, audit_date=date(2026, 11, 2), generated_on=date(2026, 11, 19),
    )


class FormatTests(SimpleTestCase):

    def test_nombres_a_la_francaise(self):
        self.assertEqual(fmt_number(704000), '704 000')
        self.assertEqual(fmt_number(58666.67), '58 666,67')
        self.assertEqual(fmt_number(12.0), '12')
        self.assertEqual(fmt_value(30.0, '%'), '30 %')
        self.assertIsNone(fmt_value(None, '€'))

    def test_reponses(self):
        self.assertEqual(fmt_answer(question('?', 'oui_non', True)), 'Oui')
        self.assertEqual(fmt_answer(question('?', 'montant', 12000)), '12 000 €')
        self.assertEqual(fmt_answer(question('?', 'date', '2026-03-12')), '12 mars 2026')
        self.assertEqual(fmt_answer(question('?', 'nombre', None, status='ignoree')), 'Sans réponse')

    def test_textes_internes_reformules(self):
        self.assertEqual(client_text("postes à retenir non définis (à valider avec Ny Aina)"),
                         'postes à retenir non définis')
        self.assertEqual(client_text("f(délai moyen de paiement) : méthode à définir"), 'f(délai moyen de paiement)')
        self.assertEqual(client_text("Secteur BTP choisi à l'onboarding"), "Secteur d'activité retenu : BTP")
        self.assertEqual(client_text("Questionnaire de l'agent terminé"), 'Questionnaire terminé')
        self.assertEqual(client_text('absent des comptes : à demander au dirigeant'), 'absent des comptes : à compléter')

    def test_contexte(self):
        ctx = context()
        self.assertEqual(len(ctx['questions']['shown']), 10)
        self.assertEqual(ctx['questions']['others'], len(QUESTIONS) - 10)
        # les questions qui alimentent le moteur passent en premier
        self.assertTrue(ctx['questions']['shown'][0]['engine'] and ctx['questions']['shown'][1]['engine'])
        self.assertTrue(ctx['loss']['partial'])
        self.assertTrue(any('estimation partielle' in limite for limite in ctx['limits']))
        self.assertTrue(any('TJM vendu' in limite for limite in context(secteur='SERVICES')['limits']))  # sigle conservé
        self.assertNotIn('Ny Aina', json.dumps(ctx, ensure_ascii=False))
        # chiffres clés : ceux des indicateurs (fixture : données publiées), CA à 0 = non publié
        self.assertEqual(ctx['financials'][2], {'label': 'Effectif', 'value': '12 salariés', 'source': 'Comptes annuels'})
        sans_ca = build_report_context(**{**ARGS, 'published': {**PUBLISHED, 'chiffre_affaires': 0}})
        self.assertEqual(sans_ca['financials'][0]['value'], 'non publié')


class RenderTests(SimpleTestCase):

    def render(self, maximum: bool = False, secteur: str = 'BTP') -> tuple[bytes, int, str]:
        pdf, pages = render_report_pdf(context(maximum, secteur))
        document = pypdfium2.PdfDocument(io.BytesIO(pdf))
        text = '\n'.join(page.get_textpage().get_text_range() for page in document)
        self.assertEqual(len(document), pages)
        return pdf, pages, text

    def test_pdf_de_10_a_12_pages(self):
        for secteur in SECTEURS:
            for maximum in (False, True):
                with self.subTest(secteur=secteur, maximum=maximum):
                    _, pages, _ = self.render(maximum, secteur)
                    self.assertGreaterEqual(pages, 10)
                    self.assertLessEqual(pages, 12)

    def test_contenu_obligatoire(self):
        pdf, _, text = self.render()
        self.assertIn('BATI DURAN SARL', text)                # page de garde
        self.assertIn('Synthèse exécutive', text)
        self.assertIn('Levier 3 sur 3', text)                  # 3 leviers à 30 jours
        self.assertIn('Réserver mon bilan stratégique', text)  # appel à l'action
        liens = [lien.get('uri') for page in pymupdf.open(stream=pdf, filetype='pdf') for lien in page.get_links()]
        self.assertIn(CALENDLY, liens)                         # lien cliquable
        for interne in ('Ny Aina', 'onboarding', "de l'agent", 'à définir'):
            self.assertNotIn(interne, text)


class ApiTests(SimpleTestCase):

    def test_rapport_jamais_genere(self):
        payload = report_payload(None)
        self.assertIsNone(payload['status'])
        self.assertFalse(payload['pdf_available'])

    def test_routes(self):
        cas = [
            ('companies:audit-report', report_controller.get_report),
            ('companies:audit-report-generate', report_controller.generate_audit_report),
            ('companies:audit-report-pdf', report_controller.download_report_pdf),
        ]
        for name, view in cas:
            with self.subTest(name=name):
                url = reverse(name, kwargs={'audit_id': 7})
                self.assertTrue(url.startswith('/api/companies/audits/7/report/'))
                self.assertIs(resolve(url).func, view)
