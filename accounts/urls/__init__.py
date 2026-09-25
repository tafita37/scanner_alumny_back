"""
Point d'entrée des routes de l'app (inclus sous /api/auth/ dans scanner/urls.py).
Chaque groupe de routes est défini dans son propre fichier du dossier `urls/`.
"""
from django.urls import include, path

app_name = 'accounts'

urlpatterns = [
    path('', include('accounts.urls.auth_urls')),
    path('me/', include('accounts.urls.profile_urls')),
    path('password/', include('accounts.urls.password_urls')),
]
