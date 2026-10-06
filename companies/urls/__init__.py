"""
Point d'entrée des routes de l'app (inclus sous /api/companies/ dans scanner/urls.py).
Chaque groupe de routes est défini dans son propre fichier du dossier `urls/`.
"""
from django.urls import include, path

app_name = 'companies'

urlpatterns = [
    path('', include('companies.urls.company_urls')),
    path('', include('companies.urls.crud_urls')),
    path('audits/', include('companies.urls.audit_urls')),
    path('documents/', include('companies.urls.document_urls')),
]
