import mimetypes
import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import Audit, Document
from ..serializers import DocumentUploadSerializer
from ..services.pdf_extraction import PdfExtractionError, extract_pdf

# Colonnes renvoyées pour un document.
DOCUMENT_FIELDS = ('id', 'original_name', 'stored_name', 'size', 'mime_type', 'created_at', 'audit_id')

# Type MIME quand ni l'extension ni le navigateur ne permettent de le connaître.
DEFAULT_MIME_TYPE = 'application/octet-stream'

PDF_MIME_TYPE = 'application/pdf'


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


def guess_mime_type(uploaded_file):
    """
    Type MIME du fichier : déduit de son extension, sinon celui annoncé par le navigateur,
    sinon DEFAULT_MIME_TYPE. Le contenu du fichier n'est pas analysé.
    """
    mime_type, _ = mimetypes.guess_type(uploaded_file.name)
    return mime_type or uploaded_file.content_type or DEFAULT_MIME_TYPE


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_documents(request, audit_id):
    """
    Upload de plusieurs documents rattachés à l'audit de l'URL
    (multipart/form-data : `files` répété une fois par fichier).
    Chaque fichier est stocké sous un nom unique (`stored_name`) ; son nom d'origine
    sa taille (octets) et son type MIME sont enregistrés en base.
    Tout est enregistré d'un bloc : en cas d'erreur, aucun fichier n'est gardé.
    """
    audit = Audit.objects.filter(pk=audit_id).first()
    if audit is None:
        return Response({'detail': 'Audit introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    serializer = DocumentUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
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
                    mime_type=guess_mime_type(uploaded_file),
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
        .values(*DOCUMENT_FIELDS)
    )
    return Response(list(rows), status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_documents(request, audit_id):
    """
    Récupère la liste des documents rattachés à un audit (liste vide s'il n'en a aucun).
    404 si l'audit n'existe pas.
    """
    if not Audit.objects.filter(pk=audit_id).exists():
        return Response({'detail': 'Audit introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    documents = Document.objects.filter(audit_id=audit_id).order_by('id').values(*DOCUMENT_FIELDS)
    return Response(list(documents), status=status.HTTP_200_OK)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_document(request, pk):
    """
    Supprime un document : sa ligne en base, puis son fichier dans UPLOAD_DIR
    (une fois la suppression validée en base). 404 si le document n'existe pas.
    """
    document = Document.objects.filter(pk=pk).first()
    if document is None:
        return Response({'detail': 'Document introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    file_path = Path(settings.UPLOAD_DIR) / document.stored_name
    with transaction.atomic():
        document.delete()
        # Fichier déjà absent du disque : la suppression en base suffit.
        transaction.on_commit(lambda: file_path.unlink(missing_ok=True))
    return Response(status=status.HTTP_204_NO_CONTENT)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def extract_document(request, pk):
    """
    Extrait le texte (page par page) et les tableaux d'un document PDF déjà uploadé.
    Les pages sans texte exploitable sont marquées `needs_ocr`.
    404 si le document ou son fichier n'existe pas, 415 si ce n'est pas un PDF,
    422 si le PDF est corrompu ou protégé.
    """
    document = Document.objects.filter(pk=pk).first()
    if document is None:
        return Response({'detail': 'Document introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    if document.mime_type != PDF_MIME_TYPE:
        return Response(
            {'detail': 'Seuls les PDF peuvent être extraits.'},
            status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
    file_path = Path(settings.UPLOAD_DIR) / document.stored_name
    if not file_path.is_file():
        return Response({'detail': 'Fichier introuvable sur le disque.'}, status=status.HTTP_404_NOT_FOUND)
    try:
        result = extract_pdf(file_path)
    except PdfExtractionError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    return Response({'document_id': document.pk, **result}, status=status.HTTP_200_OK)
