import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import Document
from ..serializers import DocumentUploadSerializer


def store_file(uploaded_file):
    """
    Écrit le fichier dans UPLOAD_DIR sous un nom unique (uuid + extension d'origine)
    et renvoie ce nom.
    """
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = uuid.uuid4().hex + Path(uploaded_file.name).suffix.lower()
    with open(upload_dir / stored_name, 'wb') as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)
    return stored_name


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_documents(request):
    """
    Upload de plusieurs documents rattachés à un audit
    (multipart/form-data : `files` répété une fois par fichier, `audit_id`).
    Chaque fichier est stocké sous un nom unique (`stored_name`) ; son nom d'origine
    et sa taille (octets) sont enregistrés en base.
    Tout est enregistré d'un bloc : en cas d'erreur, aucun fichier n'est gardé.
    """
    serializer = DocumentUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    audit = serializer.validated_data['audit_id']
    stored_names = []
    try:
        with transaction.atomic():
            documents = []
            for uploaded_file in serializer.validated_data['files']:
                stored_name = store_file(uploaded_file)
                stored_names.append(stored_name)
                documents.append(Document.objects.create(
                    original_name=uploaded_file.name,
                    stored_name=stored_name,
                    size=uploaded_file.size,
                    audit=audit,
                ))
    except Exception:
        # Pas de ligne en base : on ne garde pas les fichiers orphelins.
        for stored_name in stored_names:
            (Path(settings.UPLOAD_DIR) / stored_name).unlink(missing_ok=True)
        raise
    rows = (
        Document.objects
        .filter(pk__in=[document.pk for document in documents])
        .order_by('id')
        .values('id', 'original_name', 'stored_name', 'size', 'created_at', 'audit_id')
    )
    return Response(list(rows), status=status.HTTP_201_CREATED)
