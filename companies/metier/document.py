from django.db import models
from django.utils import timezone

from .audit import Audit


class Document(models.Model):
    """
    Fichier rattaché à un audit : nom d'origine fourni par l'utilisateur,
    nom unique sous lequel il est stocké, et taille en octets.
    """

    original_name = models.CharField("nom d'origine", max_length=255)
    stored_name = models.CharField('nom de stockage', max_length=255, unique=True)
    size = models.IntegerField('taille (octets)')
    created_at = models.DateField('date de création', default=timezone.localdate)
    audit = models.ForeignKey(Audit, on_delete=models.PROTECT, related_name='documents')

    class Meta:
        db_table = 'document'
        verbose_name = 'document'
        verbose_name_plural = 'documents'
        ordering = ['-created_at']

    def __str__(self):
        return self.original_name
