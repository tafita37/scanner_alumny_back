from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..services.dashboard import compute_dashboard


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard(request):
    """
    Tableau de bord sur tous les audits : compteurs, KPI (perte cumulée, délai moyen), répartition
    par secteur, audits à traiter en priorité (5 au plus) et tableau des dossiers.
    Recalculé à chaque appel (un cockpit par audit, sans LLM).
    """
    return Response(compute_dashboard(), status=status.HTTP_200_OK)
