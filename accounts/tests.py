import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

User = get_user_model()
PASSWORD = 'Motdepasse!2026'
NEW_PASSWORD = 'NouveauMdp!2026'


class AuthTestCase(APITestCase):
    def setUp(self):
        cache.clear()  # remet à zéro les compteurs de throttling
        self.user = User.objects.create_user(
            email='Jean.Dupont@Example.com', password=PASSWORD,
            first_name='Jean', last_name='Dupont',
        )

    def login(self, email='jean.dupont@example.com', password=PASSWORD):
        return self.client.post(reverse('accounts:login'), {'email': email, 'password': password})

    def authenticate(self):
        token = self.login().data['token']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        return token

    # --- Login / logout --------------------------------------------------

    def test_email_is_normalized(self):
        self.assertEqual(self.user.email, 'jean.dupont@example.com')

    def test_login_returns_token(self):
        response = self.login(email='JEAN.dupont@example.com')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['token'], Token.objects.get(user=self.user).key)
        self.assertEqual(response.data['user']['email'], 'jean.dupont@example.com')
        self.assertIn('expires_at', response.data)
        self.assertEqual(set(response.data['user']), {'id', 'email', 'first_name', 'last_name', 'is_staff'})
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_login)

    def test_login_wrong_password(self):
        response = self.login(password='mauvais')
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('token', response.data)

    def test_login_inactive_user(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.login().status_code, 400)

    def test_login_reuses_valid_token(self):
        self.assertEqual(self.login().data['token'], self.login().data['token'])

    def test_expired_token_is_rejected_and_renewed_on_login(self):
        token = self.authenticate()
        Token.objects.filter(key=token).update(created=Token.objects.get(key=token).created - timedelta(days=2))
        self.assertEqual(self.client.get(reverse('accounts:me')).status_code, 401)
        self.assertNotEqual(self.login().data['token'], token)

    def test_token_keyword_is_rejected(self):
        token = self.login().data['token']
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token}')
        self.assertEqual(self.client.get(reverse('accounts:me')).status_code, 401)

    def test_logout_deletes_token(self):
        self.authenticate()
        self.assertEqual(self.client.post(reverse('accounts:logout')).status_code, 200)
        self.assertFalse(Token.objects.filter(user=self.user).exists())
        self.assertEqual(self.client.get(reverse('accounts:me')).status_code, 401)

    def test_token_refresh(self):
        old = self.authenticate()
        response = self.client.post(reverse('accounts:token-refresh'))
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data['token'], old)
        self.assertFalse(Token.objects.filter(key=old).exists())

    # --- Profil ------------------------------------------------------------

    def test_me_returns_public_fields_only(self):
        self.authenticate()
        data = self.client.get(reverse('accounts:me')).data
        self.assertEqual(
            set(data), {'id', 'email', 'first_name', 'last_name', 'is_staff', 'date_joined', 'last_login'}
        )
        self.assertNotIn('password', data)

    def test_to_dict_never_exposes_password(self):
        self.assertEqual(self.user.to_dict('email', 'password'), {'email': 'jean.dupont@example.com'})

    def test_me_update_rejects_blank_name(self):
        self.authenticate()
        response = self.client.patch(reverse('accounts:me-update'), {'first_name': ''}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_me_requires_auth(self):
        self.assertEqual(self.client.get(reverse('accounts:me')).status_code, 401)

    def test_me_get_and_update(self):
        self.authenticate()
        self.assertEqual(self.client.get(reverse('accounts:me')).data['first_name'], 'Jean')
        response = self.client.patch(
            reverse('accounts:me-update'), {'first_name': 'Jeanne', 'email': 'pirate@x.com', 'is_staff': True}
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Jeanne')
        self.assertEqual(self.user.email, 'jean.dupont@example.com')
        self.assertFalse(self.user.is_staff)

    def test_wrong_http_method_is_rejected(self):
        self.authenticate()
        self.assertEqual(self.client.post(reverse('accounts:me')).status_code, 405)
        self.assertEqual(self.client.get(reverse('accounts:login')).status_code, 405)

    # --- Changement de mot de passe -----------------------------------------

    def test_password_change(self):
        old = self.authenticate()
        response = self.client.post(reverse('accounts:password-change'), {
            'old_password': PASSWORD, 'new_password': NEW_PASSWORD, 'new_password_confirm': NEW_PASSWORD,
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data['token'], old)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertEqual(len(mail.outbox), 1)

    def test_password_change_wrong_old_password(self):
        self.authenticate()
        response = self.client.post(reverse('accounts:password-change'), {
            'old_password': 'faux', 'new_password': NEW_PASSWORD, 'new_password_confirm': NEW_PASSWORD,
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('old_password', response.data)

    def test_password_change_validators(self):
        self.authenticate()
        response = self.client.post(reverse('accounts:password-change'), {
            'old_password': PASSWORD, 'new_password': '123', 'new_password_confirm': '123',
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('new_password', response.data)

    def test_password_change_mismatch(self):
        self.authenticate()
        response = self.client.post(reverse('accounts:password-change'), {
            'old_password': PASSWORD, 'new_password': NEW_PASSWORD, 'new_password_confirm': 'autre',
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('new_password_confirm', response.data)

    # --- Mot de passe oublié ------------------------------------------------

    def request_reset(self, email='jean.dupont@example.com'):
        return self.client.post(reverse('accounts:password-reset'), {'email': email})

    def reset_link_parts(self):
        match = re.search(r'reset-password/([^/\s]+)/([^/\s]+)', mail.outbox[-1].body)
        return match.group(1), match.group(2)

    def test_reset_request_sends_email(self):
        response = self.request_reset(email='Jean.Dupont@example.com')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['jean.dupont@example.com'])

    def test_reset_request_unknown_email_same_response(self):
        known = self.request_reset()
        unknown = self.request_reset(email='inconnu@example.com')
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(unknown.data, known.data)
        self.assertEqual(len(mail.outbox), 1)

    def test_reset_full_flow(self):
        old = self.authenticate()
        self.client.credentials()
        self.request_reset()
        uid, token = self.reset_link_parts()

        validate = self.client.post(reverse('accounts:password-reset-validate'), {'uid': uid, 'token': token})
        self.assertEqual(validate.status_code, 200)

        payload = {'uid': uid, 'token': token, 'new_password': NEW_PASSWORD, 'new_password_confirm': NEW_PASSWORD}
        response = self.client.post(reverse('accounts:password-reset-confirm'), payload)
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertFalse(Token.objects.filter(key=old).exists())

        # Lien à usage unique
        self.assertEqual(self.client.post(reverse('accounts:password-reset-confirm'), payload).status_code, 400)
        self.assertEqual(self.login(password=NEW_PASSWORD).status_code, 200)

    def test_login_is_throttled(self):
        for _ in range(10):
            self.login(password='mauvais')
        self.assertEqual(self.login().status_code, 429)

    def test_reset_invalid_link(self):
        response = self.client.post(reverse('accounts:password-reset-confirm'), {
            'uid': 'abc', 'token': 'faux', 'new_password': NEW_PASSWORD, 'new_password_confirm': NEW_PASSWORD,
        })
        self.assertEqual(response.status_code, 400)
