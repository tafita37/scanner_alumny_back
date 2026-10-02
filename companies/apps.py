from django.apps import AppConfig


class CompaniesConfig(AppConfig):
    # Les tables utilisent des SERIAL (INTEGER) comme clé primaire.
    default_auto_field = 'django.db.models.AutoField'
    name = 'companies'
    verbose_name = 'Entreprises'
