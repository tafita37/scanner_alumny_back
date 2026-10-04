from django.urls import path

from ..controllers import audit_controller

# Préfixe : audits/
urlpatterns = [
    path('create/', audit_controller.save_audit, name='audit-create'),
]
