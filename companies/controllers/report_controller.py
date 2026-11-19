import json

from django.http import FileResponse
from django.utils.text import slugify
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import Audit, Report
from ..services.cockpit import UnsupportedSectorError
from ..services.report import ReportError, generate_report, report_path


def decode(value):
    return json.loads(value) if value is not None else None


def report_payload(report: Report | None) -> dict:
    """
    Rapport renvoyé par l'API. `status` : état de la dernière génération (null : jamais généré) ;
    `content` (textes rédigés), `page_count` et `generated_at` : dernière génération réussie ;
    `pdf_available` : le PDF peut être téléchargé.
    """
    if report is None:
        return {'status': None, 'content': None, 'page_count': None, 'errors': None, 'input_tokens': 0,
                'output_tokens': 0, 'generated_at': None, 'pdf_available': False}
    path = report_path(report)
    return {
        'status': report.status,
        'content': decode(report.content),
        'page_count': report.page_count,
        'errors': decode(report.errors),
        'input_tokens': report.input_tokens,
        'output_tokens': report.output_tokens,
        'generated_at': report.generated_at.isoformat() if report.generated_at else None,
        'pdf_available': path is not None and path.is_file(),
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_report(request, audit_id):
    """
    Rapport de l'audit (dernière version), sans le PDF. Champs à null si aucun rapport n'a été généré.
    404 si l'audit n'existe pas.
    """
    if not Audit.objects.filter(pk=audit_id).exists():
        return Response({'detail': 'Audit introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    return Response(report_payload(Report.objects.filter(audit_id=audit_id).first()), status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_audit_report(request, audit_id):
    """
    Génère le rapport PDF de l'audit (rédaction par le LLM puis mise en page : la réponse peut prendre
    une à deux minutes) et remplace la version précédente. Renvoie le rapport : statut `ok` ou `erreur`
    (`errors` dit pourquoi ; la version précédente reste disponible).
    404 si l'audit n'existe pas ; 409 si le rapport ne peut pas être généré (questionnaire non terminé,
    génération déjà en cours, lien Calendly non configuré) ; 422 si le secteur n'a pas de moteur de calcul.
    """
    try:
        report = generate_report(audit_id)
    except Audit.DoesNotExist:
        return Response({'detail': 'Audit introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    except ReportError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
    except UnsupportedSectorError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    return Response(report_payload(report), status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def download_report_pdf(request, audit_id):
    """
    PDF du rapport de l'audit (dernière version). Téléchargement par défaut ; `?disposition=inline`
    pour l'afficher dans le navigateur (aperçu).
    404 si l'audit n'existe pas ou n'a pas de PDF.
    """
    report = Report.objects.select_related('audit__company').filter(audit_id=audit_id).first()
    path = report_path(report) if report is not None else None
    if path is None or not path.is_file():
        return Response({'detail': "Aucun rapport PDF pour cet audit."}, status=status.HTTP_404_NOT_FOUND)
    company = slugify(report.audit.company.company_name) or 'entreprise'
    day = report.generated_at.date().isoformat() if report.generated_at else ''
    return FileResponse(
        open(path, 'rb'),
        as_attachment=request.query_params.get('disposition') != 'inline',
        filename=f'audit-alumny-{company}-{day}.pdf',
        content_type='application/pdf',
    )
