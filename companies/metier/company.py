from django.db import models

from .ceo_info import CeoInfo
from .city import City
from .company_type import CompanyType
from .industry import Industry


class Company(models.Model):
    """Entreprise (unité légale) identifiée par son numéro SIREN (9 chiffres)."""

    siren_number = models.CharField('numéro SIREN', max_length=9, unique=True)
    company_name = models.CharField('raison sociale', max_length=255)
    naf_code = models.CharField('code NAF', max_length=6)
    creation_date = models.DateField('date de création')
    industry = models.ForeignKey(Industry, on_delete=models.PROTECT, related_name='companies')
    city = models.ForeignKey(City, on_delete=models.PROTECT, related_name='companies')
    ceo_info = models.ForeignKey(CeoInfo, on_delete=models.PROTECT, related_name='companies')
    company_type = models.ForeignKey(CompanyType, on_delete=models.PROTECT, related_name='companies')

    class Meta:
        db_table = 'company'
        verbose_name = 'entreprise'
        verbose_name_plural = 'entreprises'
        ordering = ['company_name']

    def __str__(self):
        return f'{self.company_name} ({self.siren_number})'
