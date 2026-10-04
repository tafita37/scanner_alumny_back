from django.db import models

from .company import Company


class Audit(models.Model):
    """
    Données publiées d'un établissement (SIRET, 14 chiffres) d'une entreprise :
    effectif et chiffre d'affaires pour une année de publication.
    """

    siret_number = models.CharField('numéro SIRET', max_length=14, unique=True)
    head_count = models.IntegerField('effectif')
    revenue = models.FloatField("chiffre d'affaires")
    profit = models.FloatField("bénéfice")
    # La colonne SQL est orthographiée `publciation_year`.
    publication_year = models.IntegerField('année de publication', db_column='publciation_year')
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='audits')

    class Meta:
        db_table = 'audit'
        verbose_name = 'audit'
        verbose_name_plural = 'audits'
        ordering = ['-publication_year']

    def __str__(self):
        return f'{self.siret_number} ({self.publication_year})'
