import json

from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..metier.questionnaire import StatutQuestionnaire
from ..metier.question import StatutQuestion
from ..models import Audit, Document, Question, Questionnaire
from ..serializers import QuestionAnswerSerializer
from ..services.cockpit import askable_entries
from ..services.questionnaire import QuestionnaireError, generate_round, is_finished
from ..services.structuring import to_json


def decode(value):
    return json.loads(value) if value is not None else None


def question_payload(question: Question, document_ids: list[int]) -> dict:
    """Question renvoyée par l'API, avec ses colonnes JSON décodées."""
    return {
        'id': question.pk,
        'display_order': question.display_order,
        'label': question.label,
        'rationale': question.rationale,
        'answer_type': question.answer_type,
        'choices': decode(question.choices),
        'unit': question.unit,
        'variable': question.variable,
        'document_ids': document_ids,
        'suggested_answer': decode(question.suggested_answer),
        'suggested_answer_source': question.suggested_answer_source,
        'status': question.status,
        'answer': decode(question.answer),
    }


def questionnaire_payload(questionnaire: Questionnaire) -> dict:
    """Tour renvoyé par l'API, avec ses questions (préchargées par `rounds_with_questions`)."""
    return {
        'id': questionnaire.pk,
        'round_number': questionnaire.round_number,
        'status': questionnaire.status,
        'analysis': questionnaire.analysis,
        'input_tokens': questionnaire.input_tokens,
        'output_tokens': questionnaire.output_tokens,
        'questions': [
            question_payload(question, [document.pk for document in question.documents.all()])
            for question in questionnaire.questions.all()
        ],
    }


def rounds_with_questions():
    """Tours avec leurs questions (dans l'ordre d'affichage) et les documents de chacune, en 3 requêtes."""
    questions = (
        Question.objects
        .order_by('display_order')
        .prefetch_related(Prefetch('documents', queryset=Document.objects.only('id').order_by('id')))
    )
    return Questionnaire.objects.order_by('round_number').prefetch_related(Prefetch('questions', queryset=questions))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_questionnaires(request, audit_id):
    """
    Tours du questionnaire adaptatif de l'audit (tous statuts), du premier au dernier, avec leurs
    questions. `finished` : le questionnaire est terminé (dernier tour « ok » sans question et
    aucune entrée obligatoire du moteur de calcul à demander ; sinon un tour supplémentaire peut
    être généré).
    404 si l'audit n'existe pas.
    """
    audit = Audit.objects.select_related('company__industry').filter(pk=audit_id).first()
    if audit is None:
        return Response({'detail': 'Audit introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    rounds = list(rounds_with_questions().filter(audit_id=audit_id))
    return Response(
        {'finished': is_finished(rounds, askable_entries(audit)),
         'questionnaires': [questionnaire_payload(r) for r in rounds]},
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_questionnaire(request, audit_id):
    """
    Génère le tour suivant du questionnaire adaptatif de l'audit par l'agent IA (plusieurs appels
    au LLM : la réponse peut prendre une à deux minutes) et l'enregistre.
    Renvoie le tour : statut `ok` (questions enregistrées ; aucune question et aucune entrée
    obligatoire du moteur à demander : questionnaire terminé, `finished` = true) ou `erreur`
    (`errors` dit pourquoi ; relancer la génération reprend ce tour). `tool_calls` : appels de tools de l'agent pendant l'enquête (arguments anonymisés).
    404 si l'audit n'existe pas ; 409 si le tour ne peut pas être généré (aucun document extrait,
    tour déjà en cours, questions du dernier tour sans réponse, questionnaire terminé).
    """
    try:
        result = generate_round(audit_id)
    except Audit.DoesNotExist:
        return Response({'detail': 'Audit introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    except QuestionnaireError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
    questionnaire = rounds_with_questions().get(pk=result.questionnaire.pk)
    finished = questionnaire.status == StatutQuestionnaire.OK and not questionnaire.questions.all()
    if finished:
        # Un tour sans question n'est validé que s'il ne reste aucune entrée obligatoire ; recontrôlé
        # pour le cas où les données ont changé pendant la génération.
        audit = Audit.objects.select_related('company__industry').get(pk=audit_id)
        finished = is_finished([questionnaire], askable_entries(audit))
    return Response(
        {
            **questionnaire_payload(questionnaire),
            'finished': finished,
            'errors': result.errors,
            'tool_calls': result.tool_calls,
        },
        status=status.HTTP_200_OK,
    )


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def answer_question(request, pk):
    """
    Réponse du dirigeant à une question (body JSON) :
    - {"status": "repondue", "answer": <valeur>} : valeur du type de la question (nombre pour montant,
      pourcentage et nombre ; "AAAA-MM-JJ" pour date ; true/false pour oui_non ; une des options pour
      choix ; texte sinon). Confirmer la réponse proposée : renvoyer la même valeur ; la corriger :
      en envoyer une autre.
    - {"status": "ignoree"} : le dirigeant ne répond pas ;
    - {"status": "en_attente"} : annule la réponse ou l'abandon.
    Renvoie la question mise à jour.
    404 si la question n'existe pas, 400 si la réponse ne correspond pas au type de la question,
    409 si le tour suivant a déjà été généré (il s'appuie sur les réponses de ce tour).
    """
    question = Question.objects.select_related('questionnaire').filter(pk=pk).first()
    if question is None:
        return Response({'detail': 'Question introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    later_round = Questionnaire.objects.filter(
        audit_id=question.questionnaire.audit_id,
        round_number__gt=question.questionnaire.round_number,
        status__in=[StatutQuestionnaire.OK, StatutQuestionnaire.EN_COURS],
    ).exists()
    if later_round:
        return Response(
            {'detail': 'Le tour suivant a déjà été généré à partir des réponses de ce tour : la réponse ne peut plus changer.'},
            status=status.HTTP_409_CONFLICT,
        )
    serializer = QuestionAnswerSerializer(data=request.data, context={'question': question})
    serializer.is_valid(raise_exception=True)
    question.status = serializer.validated_data['status']
    question.answer = to_json(serializer.validated_data.get('answer')) if question.status == StatutQuestion.REPONDUE else None
    question.answered_at = None if question.status == StatutQuestion.EN_ATTENTE else timezone.localdate()
    question.save(update_fields=['status', 'answer', 'answered_at'])
    return Response(
        question_payload(question, list(question.documents.order_by('id').values_list('id', flat=True))),
        status=status.HTTP_200_OK,
    )
