from django.urls import path

from ..controllers import audit_controller, document_controller

# Préfixe : audits/
urlpatterns = [
    path('', audit_controller.list_audits, name='audit-list'),
    path('create/', audit_controller.save_audit, name='audit-create'),
    path('<int:audit_id>/documents/', document_controller.get_documents, name='audit-documents'),
    path(
        '<int:audit_id>/documents/upload/',
        document_controller.upload_documents,
        name='audit-documents-upload',
    ),
]
