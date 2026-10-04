from django.db import models


class Industry(models.Model):
    """Secteur d'activité d'une entreprise."""

    name = models.CharField('nom', max_length=50, unique=True)
    description = models.TextField('description')

    class Meta:
        db_table = 'industry'
        verbose_name = 'secteur'
        verbose_name_plural = 'secteurs'
        ordering = ['name']

    def __str__(self):
        return self.name
