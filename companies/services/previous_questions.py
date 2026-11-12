"""
Questions déjà posées lors des tours précédents du questionnaire adaptatif d'un audit, avec
leurs réponses : c'est ce qui permet au LLM de ne pas reposer une question, de creuser une
réponse et de juger s'il reste quelque chose d'important à demander.

Seules les réponses en texte libre peuvent contenir des données personnelles (« mon client
M. Dupont paie en retard ») : elles sont anonymisées comme le texte des documents. Les autres
réponses (montant, pourcentage, nombre, date, oui/non, choix proposé par le LLM) et les questions
elles-mêmes (rédigées par le LLM à partir d'un contexte déjà masqué) sont renvoyées telles quelles.

Ces questions sont placées par le code dans le message initial de l'agent du questionnaire :
l'agent en a toujours besoin, ce n'est donc pas un tool (il coûterait un appel au LLM de plus à
chaque tour).
"""
import json

from django.db.models import Prefetch

from ..models import Question, Questionnaire
from ..metier.question import TypeReponse
from ..metier.questionnaire import StatutQuestionnaire
from .anonymization import PseudonymMapping, anonymize_text


def read_answer(question: Question, mapping: PseudonymMapping):
    """Réponse de la question (valeur JSON décodée), anonymisée si c'est du texte libre."""
    if question.answer is None:
        return None
    answer = json.loads(question.answer)
    if question.answer_type == TypeReponse.TEXTE and isinstance(answer, str) and answer.strip():
        return anonymize_text(answer, mapping)
    return answer


def read_previous_questions(audit_id: int, mapping: PseudonymMapping) -> list[dict]:
    """
    Tours déjà générés (statut « ok ») de l'audit, du premier au dernier, avec leurs questions.
    Un tour en cours de génération ou en erreur n'est pas renvoyé.
    `mapping` reçoit les jetons des données personnelles trouvées dans les réponses : l'appelant
    le garde pour remettre les vraies valeurs dans la sortie du LLM (`deanonymize`). Une seule
    correspondance pour tous les tours : une même personne reçoit le même jeton partout.
    """
    questionnaires = (
        Questionnaire.objects
        .filter(audit_id=audit_id, status=StatutQuestionnaire.OK)
        .order_by('round_number')
        .prefetch_related(Prefetch('questions', queryset=Question.objects.order_by('display_order')))
    )
    return [
        {
            'tour': questionnaire.round_number,
            'analyse': questionnaire.analysis,
            'questions': [
                {
                    'question': question.label,
                    'justification': question.rationale,
                    'type_reponse': question.answer_type,
                    'unite': question.unit,
                    'statut': question.status,
                    'reponse': read_answer(question, mapping),
                }
                for question in questionnaire.questions.all()
            ],
        }
        for questionnaire in questionnaires
    ]
