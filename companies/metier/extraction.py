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
    éventuelles, nombre de tentatives et tokens consommés (cumul de tous les
    appels au LLM : classification + chaque tentative d'extraction).
    `json_pages` : texte du document vu par cette extraction, page par page
    (`[{"number": 1, "text": "..."}, ...]`, Markdown de Docling, en clair) ; relu par les tools
    de l'agent du questionnaire, qui l'anonymisent avant de l'envoyer au LLM. Pour des comptes
    annuels natifs, seules les pages utiles ont été converties et sont donc présentes.
    """

    extraction_date = models.DateField("date d'extraction", default=timezone.localdate)
    status = models.CharField(
        'statut', max_length=20, choices=StatutExtraction.choices, default=StatutExtraction.EN_COURS
    )
    json_extraction = models.TextField('extraction (JSON)', null=True, blank=True)
    json_variables = models.TextField('variables (JSON)', null=True, blank=True)
    json_pages = models.TextField('pages du document (JSON)', null=True, blank=True)
    errors = models.TextField('erreurs', null=True, blank=True)
    attempts = models.IntegerField('tentatives', default=0)
    input_tokens = models.IntegerField("tokens d'entrée", default=0)
    output_tokens = models.IntegerField('tokens de sortie', default=0)
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name='extractions')

    class Meta:
        db_table = 'extraction'
        verbose_name = 'extraction'
        verbose_name_plural = 'extractions'
        ordering = ['-extraction_date']

    def __str__(self):
        return f'{self.document} ({self.status})'
