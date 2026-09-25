from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import AuthenticationFailed


def token_ttl():
    """Durée de validité d'un token (settings.AUTH_TOKEN_TTL, en secondes)."""
    return timedelta(seconds=getattr(settings, 'AUTH_TOKEN_TTL', 60 * 60 * 24))


def token_expires_at(token):
    return token.created + token_ttl()


def is_token_expired(token):
    return timezone.now() >= token_expires_at(token)


def token_payload(token, user):
    """Corps de réponse standard renvoyé quand un token est délivré."""
    return {
        'token': token.key,
        'expires_at': token_expires_at(token),
        'user': user.to_dict('id', 'email', 'first_name', 'last_name', 'is_staff'),
    }


def get_fresh_token(user):
    """Retourne le token valide de l'utilisateur, ou en crée un nouveau s'il a expiré."""
    token, created = Token.objects.get_or_create(user=user)
    if not created and is_token_expired(token):
        token.delete()
        token = Token.objects.create(user=user)
    return token


def rotate_token(user):
    """Invalide le token actuel de l'utilisateur et en crée un nouveau."""
    Token.objects.filter(user=user).delete()
    return Token.objects.create(user=user)


class ExpiringTokenAuthentication(TokenAuthentication):
    """
    Authentification par header `Authorization: Bearer <clé>`,
    avec expiration du token après AUTH_TOKEN_TTL secondes.
    """

    keyword = 'Bearer'

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if is_token_expired(token):
            token.delete()
            raise AuthenticationFailed('Le token a expiré, veuillez vous reconnecter.')
        return user, token
