from django.db import models

from .city import City


class CityPostalCode(models.Model):
    """Code postal d'une commune (une commune peut en avoir plusieurs, et inversement)."""

    postal_code = models.CharField('code postal', max_length=5)
    city = models.ForeignKey(City, on_delete=models.PROTECT, related_name='postal_codes')

    class Meta:
        db_table = 'city_postal_code'
        verbose_name = 'code postal'
        verbose_name_plural = 'codes postaux'
        ordering = ['postal_code']

    def __str__(self):
        return f'{self.postal_code} - {self.city.name}'
