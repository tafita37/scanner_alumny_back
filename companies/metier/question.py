from django.db import models

from .document import Document
from .questionnaire import Questionnaire


class TypeReponse(models.TextChoices):
    MONTANT = "montant", "Montant"
    POURCENTAGE = "pourcentage", "Pourcentage"
    NOMBRE = "nombre", "Nombre"
    DATE = "date", "Date"
    OUI_NON = "oui_non", "Oui / non"
    CHOIX = "choix", "Choix"
    TEXTE = "texte", "Texte"


class StatutQuestion(models.TextChoices):
    EN_ATTENTE = "en_attente", "En attente"
    REPONDUE = "repondue", "Répondue"
    IGNOREE = "ignoree", "Ignorée"


class Question(models.Model):
    """
    Question posée par le LLM lors d'un tour du questionnaire.
    `rationale` : pourquoi elle compte (perte financière visée) ; `answer_type` : forme attendue
    de la réponse (champ de saisie du front) ; `choices` : options si `answer_type` = choix (JSON) ;
    `documents` : documents qui ont motivé la question (table d'association `question_document`) ;
    `answer` : la réponse (JSON : nombre, booléen, texte...).
    """

    display_order = models.IntegerField("ordre d'affichage")
    label = models.TextField('question')
    rationale = models.TextField('justification')
    answer_type = models.CharField('type de réponse', max_length=20, choices=TypeReponse.choices)
    choices = models.TextField('choix (JSON)', null=True, blank=True)
    unit = models.CharField('unité', max_length=20, null=True, blank=True)
    documents = models.ManyToManyField(
        Document, verbose_name='documents concernés', db_table='question_document', related_name='questions',
        blank=True,
    )
    status = models.CharField(
        'statut', max_length=20, choices=StatutQuestion.choices, default=StatutQuestion.EN_ATTENTE
    )
    answer = models.TextField('réponse (JSON)', null=True, blank=True)
    questionnaire = models.ForeignKey(Questionnaire, on_delete=models.PROTECT, related_name='questions')

    class Meta:
        db_table = 'question'
        verbose_name = 'question'
        verbose_name_plural = 'questions'
        ordering = ['display_order']

    def __str__(self):
        return self.label
