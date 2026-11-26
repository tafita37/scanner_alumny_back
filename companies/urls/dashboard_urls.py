from django.urls import path

from ..controllers import dashboard_controller

# Préfixe : dashboard/
urlpatterns = [
    path('', dashboard_controller.get_dashboard, name='dashboard'),
]
