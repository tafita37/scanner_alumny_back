from django.urls import path

from ..controllers import document_controller

# Préfixe : documents/
urlpatterns = [
    path('upload/', document_controller.upload_documents, name='document-upload'),
]
