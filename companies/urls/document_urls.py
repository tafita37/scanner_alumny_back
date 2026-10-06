from django.urls import path

from ..controllers import document_controller

# Préfixe : documents/ — routes portant sur un document précis.
# (Liste et upload des documents d'un audit : voir audit_urls.py.)
urlpatterns = [
    path('<int:pk>/delete/', document_controller.delete_document, name='document-delete'),
]
