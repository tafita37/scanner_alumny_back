from django.db import models


class City(models.Model):
    """Commune française, identifiée par son code INSEE."""

    name = models.CharField('nom', max_length=50)
    code_insee = models.CharField('code INSEE', max_length=5, unique=True)
    department_code = models.CharField('code département', max_length=3)

    class Meta:
        db_table = 'city'
        verbose_name = 'commune'
        verbose_name_plural = 'communes'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.code_insee})'
