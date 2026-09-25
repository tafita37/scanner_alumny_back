from django.contrib.auth.signals import user_logged_in, user_logged_out
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_scope,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from ..authentication import get_fresh_token, rotate_token, token_payload
from ..serializers import LoginSerializer


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_scope('login')
def login(request):
    """email + mot de passe -> token d'authentification."""
    serializer = LoginSerializer(data=request.data, context={'request': request})
    serializer.is_valid(raise_exception=True)
    user = serializer.validated_data['user']
    token = get_fresh_token(user)
    # Met à jour last_login (receiver update_last_login de django.contrib.auth).
    user_logged_in.send(sender=user.__class__, request=request, user=user)
    return Response(token_payload(token, user), status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    """Supprime le token courant."""
    request.auth.delete()
    user_logged_out.send(sender=request.user.__class__, request=request, user=request.user)
    return Response({'detail': 'Déconnexion réussie.'}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def refresh_token(request):
    """Remplace le token courant par un nouveau (prolonge la session)."""
    token = rotate_token(request.user)
    return Response(token_payload(token, request.user), status=status.HTTP_200_OK)
