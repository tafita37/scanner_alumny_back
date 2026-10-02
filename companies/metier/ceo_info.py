from django.db import models

from .individual import Individual


class CeoInfo(models.Model):
    """
    Dirigeant d'une entreprise : la personne (`individual`) et ses coordonnées
    dans le cadre de cette fonction (email / téléphone pro, intitulé du poste).
    """

    email = models.EmailField('adresse email', max_length=50)
    phone_number = models.CharField('téléphone', max_length=50)
    job_title = models.CharField('fonction', max_length=50)
    individual = models.ForeignKey(Individual, on_delete=models.PROTECT, related_name='ceo_infos')

    class Meta:
        db_table = 'ceo_info'
        verbose_name = 'dirigeant'
        verbose_name_plural = 'dirigeants'
        ordering = ['individual__name', 'individual__first_name']

    def __str__(self):
        return f'{self.individual} ({self.job_title})'

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.lower()
        super().save(*args, **kwargs)
