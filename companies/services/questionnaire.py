"""
Génération d'un tour du questionnaire adaptatif d'un audit, par l'agent du dossier `questionnaire`.

Déroulé de `generate_round` :
1. Vérifications et création du tour « en_cours », sous verrou de l'audit (`prepare_round`) :
   deux demandes simultanées ne génèrent pas deux fois le même tour.
2. Préparation, avec une seule correspondance de jetons pour tout le tour : contexte de l'audit
   (et alias des parties), questions précédentes (masquées avec les mêmes alias et jetons), tools
   liés à l'audit.
3. Génération par le graphe (enquête, rédaction, validation) : long (plusieurs appels au LLM),
   donc hors de toute transaction.
4. Les vrais noms sont remis dans le résultat (jetons, puis alias des parties : le dirigeant ne
   sait pas qui est PARTIE_1), puis les questions et leurs documents sont enregistrés en une
   transaction avec le statut « ok » du tour.

Un tour en erreur est relancé sur la même ligne (même numéro, tokens cumulés) : les tours « ok »
restent numérotés sans trou. Il n'y a pas de nombre maximal de tours : l'agent arrête le
questionnaire en rendant un tour sans question. Le questionnaire n'est terminé que s'il ne reste
aucune entrée obligatoire du moteur de calcul à demander (`is_finished`) : sinon un tour
supplémentaire peut être généré, même après un tour sans question.
Un tour resté « en_cours » (serveur arrêté pendant la génération) bloque l'audit : le passer en
« erreur » à la main pour le relancer.
"""
from dataclasses import dataclass, field

from django.db import transaction

from questionnaire.graphe import generer_questions

from ..models import Audit, Extraction, Question, Questionnaire
from ..metier.question import StatutQuestion
from ..metier.questionnaire import StatutQuestionnaire
from .anonymization import PseudonymMapping, deanonymize
from .audit_context import read_audit_context_with_aliases
from .calculation_tool import calculer
from .cockpit import askable_entries, has_mandatory_entries
from .investigation_tools import make_investigation_tools
from .previous_questions import read_previous_questions
from .structuring import to_json


class QuestionnaireError(Exception):
    """Le tour ne peut pas être généré ; le message est destiné à l'utilisateur."""


@dataclass
class RoundResult:
    """
    Résultat d'une génération. `errors` et `tool_calls` ne sont pas enregistrés en base : `errors`
    explique un tour en erreur, `tool_calls` ({tool, arguments}, arguments tels qu'envoyés par le
    LLM, donc anonymisés) trace l'enquête de l'agent.
    """
    questionnaire: Questionnaire
    questions: list[Question] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)


def is_finished(rounds: list[Questionnaire], entries: list[dict]) -> bool:
    """
    Questionnaire terminé : le dernier tour « ok » n'a aucune question (l'agent n'a plus rien à
    demander) et aucune entrée obligatoire du moteur ne reste à demander.
    `rounds` : tours de l'audit avec leurs questions préchargées ; `entries` : `askable_entries`.
    """
    ok_rounds = [r for r in rounds if r.status == StatutQuestionnaire.OK]
    return bool(ok_rounds) and not ok_rounds[-1].questions.all() and not has_mandatory_entries(entries)


def prepare_round(audit_id: int) -> Questionnaire:
    """
    Vérifie qu'un nouveau tour peut être généré et renvoie sa ligne au statut « en_cours » : une
    nouvelle ligne, ou celle du dernier tour s'il est en erreur.
    Après un tour sans question, un tour supplémentaire n'est possible que s'il reste une entrée
    obligatoire du moteur de calcul à demander.
    Lève QuestionnaireError (aucune extraction, tour déjà en cours, questions sans réponse au
    dernier tour, questionnaire terminé) ou Audit.DoesNotExist.
    """
    with transaction.atomic():
        audit = Audit.objects.select_related('company__industry').select_for_update(of=('self',)).get(pk=audit_id)
        if not Extraction.objects.filter(document__audit=audit).exists():
            raise QuestionnaireError("Aucun document de l'audit n'a été extrait : rien sur quoi baser des questions.")

        rounds = list(audit.questionnaires.order_by('round_number'))
        if any(r.status == StatutQuestionnaire.EN_COURS for r in rounds):
            raise QuestionnaireError('Un tour du questionnaire est déjà en cours de génération.')

        ok_rounds = [r for r in rounds if r.status == StatutQuestionnaire.OK]
        if ok_rounds:
            last_ok = ok_rounds[-1]
            statuses = list(last_ok.questions.values_list('status', flat=True))
            if not statuses and not has_mandatory_entries(askable_entries(audit)):
                raise QuestionnaireError(
                    f'Le questionnaire est terminé : le tour {last_ok.round_number} ne contenait plus aucune question.'
                )
            pending = statuses.count(StatutQuestion.EN_ATTENTE)
            if pending:
                raise QuestionnaireError(
                    f'{pending} question(s) du tour {last_ok.round_number} sans réponse : y répondre ou les '
                    'ignorer avant de générer le tour suivant.'
                )

        last = rounds[-1] if rounds else None
        if last is not None and last.status == StatutQuestionnaire.ERREUR:
            last.status = StatutQuestionnaire.EN_COURS
            last.analysis = None
            last.save(update_fields=['status', 'analysis'])
            return last
        return Questionnaire.objects.create(
            audit=audit,
            round_number=last.round_number + 1 if last else 1,
            status=StatutQuestionnaire.EN_COURS,
        )


def build_questions(questionnaire: Questionnaire, result: dict) -> list[tuple[Question, list[int]]]:
    """
    Questions à enregistrer (non sauvegardées) avec les identifiants de leurs documents, à partir du
    résultat validé du graphe, noms déjà remis. Les valeurs JSON (choix, réponse proposée) sont
    encodées comme `Question.answer`.
    """
    return [
        (
            Question(
                questionnaire=questionnaire,
                display_order=order,
                label=item['label'],
                rationale=item['rationale'],
                answer_type=item['answer_type'],
                choices=to_json(item['choices']),
                unit=item['unit'],
                variable=item.get('variable'),
                suggested_answer=to_json(item['suggested_answer']),
                suggested_answer_source=item['suggested_answer_source'],
                status=StatutQuestion.EN_ATTENTE,
            ),
            item['document_ids'],
        )
        for order, item in enumerate(result['questions'], start=1)
    ]


def save_questions(questionnaire: Questionnaire, result: dict) -> list[Question]:
    """Enregistre les questions, leurs liens vers les documents et le tour « ok », en une transaction."""
    built = build_questions(questionnaire, result)
    with transaction.atomic():
        questions = Question.objects.bulk_create([question for question, _ in built])
        Link = Question.documents.through
        Link.objects.bulk_create([
            Link(question_id=question.pk, document_id=document_id)
            for question, (_, document_ids) in zip(questions, built)
            for document_id in document_ids
        ])
        questionnaire.analysis = result['analyse']
        questionnaire.status = StatutQuestionnaire.OK
        questionnaire.save(update_fields=['analysis', 'status', 'input_tokens', 'output_tokens'])
    return questions


def generate_round(audit_id: int) -> RoundResult:
    """
    Génère et enregistre le tour suivant du questionnaire de l'audit. Le tour est « ok » (questions
    enregistrées ; aucune question : questionnaire terminé) ou « erreur » (`errors` dit pourquoi).
    Lève QuestionnaireError ou Audit.DoesNotExist si le tour ne peut pas être généré ; une erreur
    inattendue passe le tour en « erreur » puis est relevée.
    """
    questionnaire = prepare_round(audit_id)
    try:
        # Une seule correspondance pour le tour : contexte, questions précédentes, texte lu par les
        # tools et sortie du LLM partagent les mêmes jetons.
        mapping = PseudonymMapping()
        context, aliases = read_audit_context_with_aliases(audit_id)
        previous = read_previous_questions(audit_id, mapping, aliases)
        tools = make_investigation_tools(audit_id, mapping) + [calculer]
        state = generer_questions(context, previous, tools)

        questionnaire.input_tokens += state['tokens_entree']
        questionnaire.output_tokens += state['tokens_sortie']
        errors = aliases.restore(deanonymize(state['erreurs'], mapping))
        if state['statut'] != 'ok':
            questionnaire.status = StatutQuestionnaire.ERREUR
            questionnaire.save(update_fields=['status', 'input_tokens', 'output_tokens'])
            return RoundResult(questionnaire, errors=errors, tool_calls=state['appels_tools'])

        result = aliases.restore(deanonymize(state['resultat'], mapping))
        questions = save_questions(questionnaire, result)
        return RoundResult(questionnaire, questions, errors, state['appels_tools'])
    except Exception:
        # Erreur inattendue : le tour ne doit pas rester « en_cours », sinon il bloque l'audit.
        questionnaire.status = StatutQuestionnaire.ERREUR
        questionnaire.save(update_fields=['status', 'input_tokens', 'output_tokens'])
        raise
