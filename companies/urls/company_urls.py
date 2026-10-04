from django.urls import path

from ..controllers import company_controller

# Préfixe : (racine de /api/companies/)
urlpatterns = [
    path('search/', company_controller.search_by_siret, name='search-by-siret'),
    path(
        'audits_informations/<str:siret>/', 
        company_controller.get_audit_informations_by_siren, 
        name='get-audit-informations-by-siren'
    ),
]
