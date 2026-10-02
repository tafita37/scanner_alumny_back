from django.db import models


class CompanyType(models.Model):
    """
    Catégorie juridique d'une entreprise (nomenclature INSEE à 3 niveaux).
    `code` = code de la catégorie, `label` = libellé du niveau le plus fin.
    """

    label = models.CharField('libellé', max_length=200, unique=True)
    label_level_1 = models.CharField('libellé niveau 1', max_length=200)
    label_level_2 = models.CharField('libellé niveau 2', max_length=200)
    code = models.CharField('code', max_length=4, unique=True)

    class Meta:
        db_table = 'company_type'
        verbose_name = 'catégorie juridique'
        verbose_name_plural = 'catégories juridiques'
        ordering = ['code']

    def __str__(self):
        return f'{self.code} - {self.label}'
