"""
Point d'entrée des routes de l'app (inclus sous /api/companies/ dans scanner/urls.py).
Chaque groupe de routes est défini dans son propre fichier du dossier `urls/`.
"""
from django.urls import include, path

app_name = 'companies'

urlpatterns = [
    path('', include('companies.urls.company_urls')),
]
