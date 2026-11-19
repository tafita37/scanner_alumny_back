from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import Audit
from ..services.cockpit import UnsupportedSectorError, compute_cockpit


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_cockpit(request, audit_id):
    """
    Cockpit de l'audit (Module 3) : entrées, indicateurs, étapes de calcul, perte annuelle, score
    de santé et contrôles, calculés par le moteur du secteur à chaque appel (sans LLM, rien
    n'est enregistré).
    404 si l'audit n'existe pas ; 422 si son secteur n'a pas de moteur de calcul.
    """
    audit = Audit.objects.select_related('company__industry').filter(pk=audit_id).first()
    if audit is None:
        return Response({'detail': 'Audit introuvable.'}, status=status.HTTP_404_NOT_FOUND)
    try:
        cockpit = compute_cockpit(audit)
    except UnsupportedSectorError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    return Response(cockpit, status=status.HTTP_200_OK)
