import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

logger = logging.getLogger(__name__)


def build_password_reset_link(user):
    """Construit le lien (côté frontend) de réinitialisation du mot de passe."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    base_url = settings.FRONTEND_URL.rstrip('/')
    path = settings.PASSWORD_RESET_FRONTEND_PATH.format(uid=uid, token=token)
    return f'{base_url}/{path.lstrip("/")}', uid, token


def send_password_reset_email(user):
    link, uid, token = build_password_reset_link(user)
    context = {
        'user': user,
        'reset_link': link,
        'uid': uid,
        'token': token,
        'validity_hours': settings.PASSWORD_RESET_TIMEOUT // 3600,
    }
    subject = render_to_string('accounts/password_reset_subject.txt', context).strip()
    body = render_to_string('accounts/password_reset_email.txt', context)
    html = render_to_string('accounts/password_reset_email.html', context)

    message = EmailMultiAlternatives(subject, body, None, [user.email])
    message.attach_alternative(html, 'text/html')
    message.send()


def send_password_changed_email(user):
    """Notification de sécurité envoyée après tout changement de mot de passe."""
    context = {'user': user}
    subject = render_to_string('accounts/password_changed_subject.txt', context).strip()
    body = render_to_string('accounts/password_changed_email.txt', context)
    EmailMultiAlternatives(subject, body, None, [user.email]).send()


def notify_password_changed(user):
    """Envoie la notification sans jamais faire échouer la requête."""
    try:
        send_password_changed_email(user)
    except Exception:
        logger.exception("Échec d'envoi de la notification de changement de mot de passe")
