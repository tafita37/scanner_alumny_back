"""
Tests du tableau de bord sans base de données : étape, statut et motif « à traiter » déduits de
`remaining_step`, délai moyen et route.
Lancement : python manage.py test companies.tests.test_dashboard
"""
from datetime import date, datetime, timezone as dt_timezone

from django.test import SimpleTestCase
from django.urls import resolve, reverse

from companies.controllers import dashboard_controller
from companies.services.dashboard import _average_delay, audit_status, audit_step, pending_reason


class StepAndStatusTests(SimpleTestCase):
    def test_step_from_remaining_step(self):
        self.assertEqual([audit_step(r) for r in (5, 4, 3, 2, 1, 0)], [1, 2, 3, 4, 5, 5])
        self.assertEqual(audit_step(9), 1)

    def test_status_from_remaining_step(self):
        self.assertEqual(
            [audit_status(r) for r in (4, 3, 2, 1, 0)],
            ['documents_en_attente', 'en_cours_analyse', 'analyse', 'analyse', 'rapport_genere'],
        )


class PendingReasonTests(SimpleTestCase):
    def test_documents_step(self):
        self.assertEqual(pending_reason(4, None, 0, 0, 0), ('documents_manquants', None))
        self.assertEqual(pending_reason(4, None, 3, 2, 0), ('extraction_a_verifier', 2))
        self.assertIsNone(pending_reason(4, None, 3, 0, 0))

    def test_questions_step(self):
        self.assertEqual(pending_reason(3, None, 3, 1, 4), ('questions_en_attente', 4))
        self.assertIsNone(pending_reason(3, None, 3, 1, 0))

    def test_cockpit_step_has_nothing_to_do(self):
        self.assertIsNone(pending_reason(2, None, 3, 0, 2))

    def test_report_step(self):
        self.assertEqual(pending_reason(1, None, 3, 0, 0), ('rapport_a_generer', None))
        self.assertIsNone(pending_reason(1, 'en_cours', 3, 0, 0))
        self.assertEqual(pending_reason(1, 'erreur', 3, 0, 0), ('rapport_en_erreur', None))

    def test_finished_audit(self):
        self.assertIsNone(pending_reason(0, 'ok', 3, 1, 1))
        self.assertEqual(pending_reason(0, 'erreur', 3, 0, 0), ('rapport_en_erreur', None))


class AverageDelayTests(SimpleTestCase):
    def test_average(self):
        reports = [
            (date(2026, 11, 1), datetime(2026, 11, 5, 10, tzinfo=dt_timezone.utc)),
            (date(2026, 11, 10), datetime(2026, 11, 15, 10, tzinfo=dt_timezone.utc)),
        ]
        self.assertEqual(_average_delay(reports), {'valeur': 4.5, 'nb_audits': 2})

    def test_no_report(self):
        self.assertEqual(_average_delay([]), {'valeur': None, 'nb_audits': 0})


class RouteTests(SimpleTestCase):
    def test_route(self):
        url = reverse('companies:dashboard')
        self.assertEqual(url, '/api/companies/dashboard/')
        self.assertIs(resolve(url).func, dashboard_controller.get_dashboard)
