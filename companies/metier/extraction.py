from django.db import models
from django.utils import timezone

from .document import Document


class StatutExtraction(models.TextChoices):
    EN_COURS = "en_cours", "En cours"
    OK = "ok", "Terminée"
    A_VERIFIER = "a_verifier", "À vérifier"


class Extraction(models.Model):
    """
    Tentative d'extraction des données d'un document : statut, résultat brut
    (`json_extraction`), variables retenues (`json_variables`), erreurs
    éventuelles et nombre de tentatives.
    """

    extraction_date = models.DateField("date d'extraction", default=timezone.localdate)
    status = models.CharField(
        'statut', max_length=20, choices=StatutExtraction.choices, default=StatutExtraction.EN_COURS
    )
    json_extraction = models.TextField('extraction (JSON)', null=True, blank=True)
    json_variables = models.TextField('variables (JSON)', null=True, blank=True)
    errors = models.TextField('erreurs', null=True, blank=True)
    attempts = models.IntegerField('tentatives', default=0)
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name='extractions')

    class Meta:
        db_table = 'extraction'
        verbose_name = 'extraction'
        verbose_name_plural = 'extractions'
        ordering = ['-extraction_date']

    def __str__(self):
        return f'{self.document} ({self.status})'
