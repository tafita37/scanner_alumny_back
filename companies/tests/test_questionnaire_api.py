"""
Tests de l'API du questionnaire sans base de données : validation des réponses du dirigeant,
format des questions renvoyées, routes.
Lancement : python manage.py test companies.tests.test_questionnaire_api
"""
import json

from django.test import SimpleTestCase
from django.urls import resolve, reverse

from companies.controllers import questionnaire_controller
from companies.controllers.questionnaire_controller import question_payload
from companies.metier.question import Question
from companies.serializers import MAX_TEXT_ANSWER_LENGTH, QuestionAnswerSerializer


def check(answer_type: str, body: dict, choices=None):
    question = Question(answer_type=answer_type, choices=json.dumps(choices) if choices else None)
    serializer = QuestionAnswerSerializer(data=body, context={'question': question})
    return serializer.is_valid(), serializer.validated_data if serializer.is_valid() else serializer.errors


class AnswerValidationTests(SimpleTestCase):

    def test_valid_answers(self):
        cases = [
            ('montant', 340000.5),
            ('pourcentage', 5),
            ('nombre', -3),
            ('date', '2026-03-12'),
            ('oui_non', False),
            ('texte', '  Le client paie en retard.  '),
        ]
        for answer_type, answer in cases:
            with self.subTest(answer_type=answer_type):
                valid, data = check(answer_type, {'status': 'repondue', 'answer': answer})
                self.assertTrue(valid, data)
        self.assertEqual(check('texte', {'status': 'repondue', 'answer': ' Oui. '})[1]['answer'], 'Oui.')
        valid, data = check('choix', {'status': 'repondue', 'answer': '60 jours'}, ['30 jours', '60 jours'])
        self.assertTrue(valid)
        self.assertEqual(data['answer'], '60 jours')

    def test_invalid_answers(self):
        cases = [
            ('montant', '340000'),  # texte au lieu d'un nombre
            ('nombre', True),       # booléen
            ('date', '12/03/2026'),
            ('date', '2026-02-30'),
            ('oui_non', 'oui'),
            ('texte', '   '),
            ('texte', 'x' * (MAX_TEXT_ANSWER_LENGTH + 1)),
        ]
        for answer_type, answer in cases:
            with self.subTest(answer_type=answer_type, answer=str(answer)[:20]):
                valid, errors = check(answer_type, {'status': 'repondue', 'answer': answer})
                self.assertFalse(valid)
                self.assertIn('answer', errors)
        self.assertFalse(check('choix', {'status': 'repondue', 'answer': '90 jours'}, ['30 jours', '60 jours'])[0])

    def test_status(self):
        self.assertFalse(check('montant', {'status': 'repondue'})[0])  # réponse manquante
        self.assertTrue(check('montant', {'status': 'ignoree'})[0])
        self.assertTrue(check('montant', {'status': 'en_attente', 'answer': None})[0])
        self.assertFalse(check('montant', {'status': 'ignoree', 'answer': 12})[0])
        self.assertFalse(check('montant', {'status': 'inconnu'})[0])


class PayloadTests(SimpleTestCase):

    def test_json_columns_are_decoded(self):
        question = Question(
            pk=5, display_order=1, label='Délai ?', rationale='Retard.', answer_type='choix',
            choices='["30 jours", "60 jours"]', unit=None, suggested_answer='"60 jours"',
            suggested_answer_source='Facture 70, page 1', status='repondue', answer='"30 jours"',
        )
        payload = question_payload(question, [12, 70])
        self.assertEqual(payload['choices'], ['30 jours', '60 jours'])
        self.assertEqual((payload['suggested_answer'], payload['answer']), ('60 jours', '30 jours'))
        self.assertEqual(payload['document_ids'], [12, 70])
        empty = question_payload(Question(answer_type='montant', status='en_attente'), [])
        self.assertEqual((empty['choices'], empty['suggested_answer'], empty['answer']), (None, None, None))


class RoutesTests(SimpleTestCase):

    def test_routes(self):
        routes = [
            ('companies:audit-questionnaires', {'audit_id': 6}, questionnaire_controller.list_questionnaires),
            ('companies:audit-questionnaires-generate', {'audit_id': 6}, questionnaire_controller.generate_questionnaire),
            ('companies:question-answer', {'pk': 5}, questionnaire_controller.answer_question),
        ]
        for name, kwargs, view in routes:
            with self.subTest(name=name):
                self.assertIs(resolve(reverse(name, kwargs=kwargs)).func.cls, view.cls)
        self.assertEqual(reverse('companies:question-answer', kwargs={'pk': 5}), '/api/companies/questions/5/answer/')
