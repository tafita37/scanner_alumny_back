import logging

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_scope,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from ..authentication import rotate_token, token_payload
from ..emails import notify_password_changed, send_password_reset_email
from ..serializers import (
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    PasswordResetTokenSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    """Ancien + nouveau mot de passe (utilisateur connecté) -> nouveau token."""
    serializer = PasswordChangeSerializer(data=request.data, context={'request': request})
    serializer.is_valid(raise_exception=True)
    user = request.user
    user.set_password(serializer.validated_data['new_password'])
    user.save(update_fields=['password'])
    # L'ancien token est invalidé, on en renvoie un nouveau.
    token = rotate_token(user)
    notify_password_changed(user)
    return Response(token_payload(token, user), status=status.HTTP_200_OK)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_scope('password_reset')
def request_password_reset(request):
    """Mot de passe oublié : email -> envoi d'un lien de réinitialisation."""
    serializer = PasswordResetRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    email = serializer.validated_data['email']

    user = User.objects.filter(email=email, is_active=True).first()
    if user is not None and user.has_usable_password():
        try:
            send_password_reset_email(user)
        except Exception:
            logger.exception("Échec d'envoi de l'email de réinitialisation")

    # Réponse identique que le compte existe ou non (pas d'énumération des emails).
    return Response(
        {'detail': 'Si un compte correspond à cet email, un lien de réinitialisation a été envoyé.'},
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_scope('password_reset')
def validate_password_reset(request):
    """uid + token -> vérifie que le lien reçu par email est encore valide."""
    serializer = PasswordResetTokenSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return Response({'detail': 'Lien valide.'}, status=status.HTTP_200_OK)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_scope('password_reset')
def confirm_password_reset(request):
    """uid + token + nouveau mot de passe -> réinitialise le mot de passe."""
    serializer = PasswordResetConfirmSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.validated_data['user']
    # Changer le mot de passe invalide aussi le token de réinitialisation (usage unique).
    user.set_password(serializer.validated_data['new_password'])
    user.save(update_fields=['password'])
    # Déconnecte toutes les sessions API existantes.
    Token.objects.filter(user=user).delete()
    notify_password_changed(user)
    return Response(
        {'detail': 'Mot de passe réinitialisé, vous pouvez vous connecter.'},
        status=status.HTTP_200_OK,
    )
