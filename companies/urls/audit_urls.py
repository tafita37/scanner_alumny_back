from django.urls import path

from ..controllers import audit_controller

# Préfixe : audits/
urlpatterns = [
    path('', audit_controller.list_audits, name='audit-list'),
    path('create/', audit_controller.save_audit, name='audit-create'),
]
