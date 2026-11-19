"""
Cockpit d'un audit (Module 3) : rassemble les données d'entrée du moteur de calcul de son secteur
(`structuration.moteurs`) et l'appelle. Rien n'est enregistré : le cockpit est recalculé à chaque
appel (quelques requêtes SQL, aucun appel au LLM), comme les indicateurs.

Données d'entrée :
- les indicateurs de l'audit (`compute_indicators`) ;
- les réponses du dirigeant aux questions rattachées à une entrée du moteur (`Question.variable`),
  lues dans les tours « ok » du questionnaire ;
- l'état du questionnaire (nombre de tours « ok », dernier tour sans question).
"""
import json

from django.db.models import Count

from structuration.moteurs import calculer_cockpit, entrees_a_demander

from ..models import Question
from ..metier.questionnaire import StatutQuestionnaire
from .indicators import compute_indicators


class UnsupportedSectorError(Exception):
    """Le secteur de l'audit n'a pas de moteur de calcul ; le message est destiné à l'utilisateur."""


def audit_sector(audit) -> str:
    return audit.company.industry.name.upper()


def read_engine_answers(audit) -> dict:
    """
    Réponses aux questions rattachées à une entrée du moteur, par clé d'entrée :
    {cle: {"statut", "valeur", "tour"}}. Si une entrée a été demandée plusieurs fois, la question
    du tour le plus récent l'emporte. Seuls les tours « ok » comptent.
    """
    questions = (
        Question.objects
        .filter(questionnaire__audit=audit, questionnaire__status=StatutQuestionnaire.OK, variable__isnull=False)
        .order_by('questionnaire__round_number', 'display_order')
        .values('variable', 'status', 'answer', 'questionnaire__round_number')
    )
    answers = {}
    for question in questions:
        answers[question['variable']] = {
            'statut': question['status'],
            'valeur': json.loads(question['answer']) if question['answer'] is not None else None,
            'tour': question['questionnaire__round_number'],
        }
    return answers


def read_questionnaire_state(audit) -> dict:
    """Nombre de tours « ok » et si le dernier n'a aucune question (l'agent n'avait plus rien à demander)."""
    rounds = list(
        audit.questionnaires
        .filter(status=StatutQuestionnaire.OK)
        .order_by('round_number')
        .annotate(nb_questions=Count('questions'))
        .values_list('nb_questions', flat=True)
    )
    return {'tours_ok': len(rounds), 'dernier_tour_vide': bool(rounds) and rounds[-1] == 0}


def _engine(audit, indicators: dict | None) -> tuple[dict, dict]:
    """(cockpit, réponses du dirigeant). Lève UnsupportedSectorError."""
    if indicators is None:
        indicators = compute_indicators(audit)
    answers = read_engine_answers(audit)
    try:
        cockpit = calculer_cockpit(audit_sector(audit), indicators, answers, read_questionnaire_state(audit))
    except ValueError as exc:
        raise UnsupportedSectorError(str(exc)) from exc
    return cockpit, answers


def compute_cockpit(audit, indicators: dict | None = None) -> dict:
    """
    Cockpit de l'audit (format commenté au-dessus de `getCockpit` dans le front).
    `audit` : avec `company__industry` chargé de préférence. `indicators` : résultat de
    `compute_indicators(audit)` s'il a déjà été calculé. Lève UnsupportedSectorError.
    """
    return _engine(audit, indicators)[0]


def askable_entries(audit, indicators: dict | None = None) -> list[dict]:
    """
    Entrées du moteur que l'agent du questionnaire peut demander (`entrees_a_demander`) :
    {cle, label, unite, valeur, source, obligatoire}. Liste vide si le secteur n'a pas de moteur.
    """
    try:
        cockpit, answers = _engine(audit, indicators)
    except UnsupportedSectorError:
        return []
    return entrees_a_demander(cockpit['entrees'], answers)


def has_mandatory_entries(entries: list[dict]) -> bool:
    """Il reste au moins une entrée manquante jamais demandée au dirigeant."""
    return any(entry['obligatoire'] for entry in entries)
