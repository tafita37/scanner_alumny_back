from django.db import models

from .audit import Audit


class StatutRapport(models.TextChoices):
    EN_COURS = "en_cours", "En cours"
    OK = "ok", "Généré"
    ERREUR = "erreur", "Erreur"


class Report(models.Model):
    """
    Rapport PDF d'un audit, remis au client : une seule ligne par audit, seule la dernière version
    est conservée (une régénération remplace le texte et le fichier).
    `status` : état de la dernière génération. `content` et `stored_name` sont ceux de la dernière
    génération réussie : ils restent en place si une régénération échoue (`errors` dit pourquoi).
    `content` : textes rédigés par le LLM (JSON `rapport.schemas.RapportRedige`, vrais noms remis).
    `stored_name` : nom du PDF dans UPLOAD_DIR/reports (uuid).
    """

    status = models.CharField(
        'statut', max_length=20, choices=StatutRapport.choices, default=StatutRapport.EN_COURS
    )
    content = models.TextField('textes rédigés (JSON)', null=True, blank=True)
    stored_name = models.CharField('nom de stockage du PDF', max_length=255, null=True, blank=True)
    page_count = models.IntegerField('nombre de pages', null=True, blank=True)
    errors = models.TextField('erreurs de la dernière génération (JSON)', null=True, blank=True)
    input_tokens = models.IntegerField("tokens d'entrée", default=0)
    output_tokens = models.IntegerField('tokens de sortie', default=0)
    generated_at = models.DateTimeField('date de génération', null=True, blank=True)
    audit = models.OneToOneField(Audit, on_delete=models.PROTECT, related_name='report')

    class Meta:
        db_table = 'report'
        verbose_name = 'rapport'
        verbose_name_plural = 'rapports'

    def __str__(self):
        return f'Rapport {self.audit}'
