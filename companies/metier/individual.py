from django.db import models


class Individual(models.Model):
    """Personne physique. `name` = nom, `first_name` = prénom."""

    name = models.CharField('nom', max_length=100)
    first_name = models.CharField('prénom', max_length=100)
    email = models.EmailField('adresse email', max_length=50, unique=True)
    phone_number = models.CharField('téléphone', max_length=50, unique=True)

    class Meta:
        db_table = 'individual'
        verbose_name = 'personne'
        verbose_name_plural = 'personnes'
        ordering = ['name', 'first_name']

    def __str__(self):
        return f'{self.first_name} {self.name}'

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.lower()
        super().save(*args, **kwargs)
