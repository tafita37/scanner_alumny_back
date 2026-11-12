from django.db import models

from .audit import Audit


class StatutQuestionnaire(models.TextChoices):
    EN_COURS = "en_cours", "En cours"
    OK = "ok", "Généré"
    ERREUR = "erreur", "Erreur"


class Questionnaire(models.Model):
    """
    Un tour du questionnaire adaptatif d'un audit : lot de questions générées en une fois par le
    LLM, à partir des extractions, des indicateurs et des réponses aux tours précédents.
    `analysis` : synthèse du LLM (ce qu'il a compris, ce qui manque).
    Un tour « ok » sans aucune question signifie que le LLM n'a plus rien d'important à demander :
    le questionnaire de l'audit est terminé.
    """

    round_number = models.IntegerField('tour')
    status = models.CharField(
        'statut', max_length=20, choices=StatutQuestionnaire.choices, default=StatutQuestionnaire.EN_COURS
    )
    analysis = models.TextField('analyse', null=True, blank=True)
    input_tokens = models.IntegerField("tokens d'entrée", default=0)
    output_tokens = models.IntegerField('tokens de sortie', default=0)
    audit = models.ForeignKey(Audit, on_delete=models.PROTECT, related_name='questionnaires')

    class Meta:
        db_table = 'questionnaire'
        verbose_name = 'questionnaire'
        verbose_name_plural = 'questionnaires'
        ordering = ['round_number']
        # constraints = [
        #     models.UniqueConstraint(fields=['audit', 'round_number'], name='questionnaire_audit_round_unique'),
        # ]

    def __str__(self):
        return f'{self.audit} - tour {self.round_number}'
