from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..serializers import ProfileUpdateSerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_profile(request):
    """Profil de l'utilisateur connecté."""
    return Response(
        request.user.to_dict('id', 'email', 'first_name', 'last_name', 'is_staff', 'date_joined', 'last_login'),
        status=status.HTTP_200_OK,
    )


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_profile(request):
    """Modification partielle du profil : seuls first_name et last_name sont modifiables."""
    serializer = ProfileUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = request.user
    changes = serializer.validated_data
    if changes:
        for field, value in changes.items():
            setattr(user, field, value)
        user.save(update_fields=list(changes))
    return Response(user.to_dict('id', 'email', 'first_name', 'last_name'), status=status.HTTP_200_OK)
