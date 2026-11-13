"""
Tests du tool `calculer` de l'agent du questionnaire : ni base de données ni LLM.
Lancement : python manage.py test companies.tests.test_calculation_tool
"""
import json

from django.test import SimpleTestCase

from companies.services.calculation_tool import (
    MAX_CALCULATIONS,
    CalculationError,
    calculate,
    calculer,
    evaluate,
)


class EvaluateTests(SimpleTestCase):

    def test_arithmetic(self):
        self.assertEqual(evaluate('(1200000 - 870000) / 1200000 * 100'), 27.5)
        self.assertEqual(evaluate('45000 * 0.10 * 240 / 365'), 2958.90411)
        self.assertEqual(evaluate('2 ** 10'), 1024)
        self.assertEqual(evaluate('-(3 - 5)'), 2)

    def test_functions(self):
        self.assertEqual(evaluate('max(75, 62, 90) - 30'), 60)
        self.assertEqual(evaluate('min(3, 1.5)'), 1.5)
        self.assertEqual(evaluate('abs(-12.5)'), 12.5)
        self.assertEqual(evaluate('round(2958.904, 2)'), 2958.9)

    def test_float_noise_is_rounded(self):
        self.assertEqual(evaluate('0.1 + 0.2'), 0.3)

    def test_whole_results_are_integers(self):
        result = evaluate('870000 / 2')
        self.assertEqual(result, 435000)
        self.assertIsInstance(result, int)

    def test_code_is_refused(self):
        for expression in (
            "__import__('os').remove('x')",
            'open("fichier.txt")',
            '(1).__class__',
            '[1, 2]',
            '"texte"',
            'True + 1',
            'lambda: 1',
            'sum(1, 2)',
        ):
            with self.subTest(expression=expression), self.assertRaises(CalculationError):
                evaluate(expression)

    def test_helpful_errors(self):
        cases = {
            '1 / 0': 'division par zéro',
            'ca - 870000': '« ca » inconnu',
            '45000 * 0,10': 'virgule',
            '1 200 000 - 870000': 'séparateur de milliers',
            '100 % 7': 'opérateur non autorisé',
            '9 ** 9 ** 9': 'trop grand',
            '(-8) ** 0.5': 'non réel',
            '1e308 * 10': 'infini',
            '': 'vide',
            '1 + ' * 100 + '1': 'trop longue',
            'round(2.5, 1.5)': 'arguments invalides',
            'max()': 'arguments invalides',
        }
        for expression, message in cases.items():
            with self.subTest(expression=expression), self.assertRaises(CalculationError) as raised:
                evaluate(expression)
            self.assertIn(message, str(raised.exception))


class ToolTests(SimpleTestCase):

    def test_each_calculation_has_its_result_or_error(self):
        result = calculate([
            {'libelle': 'écart CA (%)', 'expression': '(1200000 - 870000) / 1200000 * 100'},
            {'libelle': 'erreur', 'expression': '1 / 0'},
            {'libelle': 'retard max', 'expression': 'max(75, 62, 90) - 30'},
        ])
        self.assertEqual(result['resultats'], [
            {'libelle': 'écart CA (%)', 'expression': '(1200000 - 870000) / 1200000 * 100', 'resultat': 27.5},
            {'libelle': 'erreur', 'expression': '1 / 0', 'erreur': 'division par zéro'},
            {'libelle': 'retard max', 'expression': 'max(75, 62, 90) - 30', 'resultat': 60},
        ])

    def test_number_of_calculations(self):
        self.assertIn('erreur', calculate([]))
        too_many = [{'libelle': str(i), 'expression': '1'} for i in range(MAX_CALCULATIONS + 1)]
        self.assertIn('erreur', calculate(too_many))

    def test_langchain_tool(self):
        """Appel comme le ferait l'agent : arguments validés par le schéma, réponse en JSON."""
        output = calculer.invoke({'calculs': [{'libelle': 'total', 'expression': '1500 + 2500'}]})
        self.assertEqual(json.loads(output), {'resultats': [{'libelle': 'total', 'expression': '1500 + 2500', 'resultat': 4000}]})
        self.assertEqual(calculer.name, 'calculer')
