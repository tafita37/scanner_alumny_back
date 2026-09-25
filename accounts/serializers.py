from django.contrib.auth import authenticate, get_user_model, password_validation
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers

User = get_user_model()


class ProfileUpdateSerializer(serializers.Serializer):
    """Champs modifiables par l'utilisateur lui-même (les autres sont ignorés)."""

    first_name = serializers.CharField(max_length=150, required=False)
    last_name = serializers.CharField(max_length=150, required=False)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False, write_only=True)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get('request'),
            username=attrs['email'].lower(),
            password=attrs['password'],
        )
        # authenticate() renvoie None aussi pour un compte désactivé :
        # on garde un message générique pour ne pas révéler l'existence du compte.
        if user is None:
            raise serializers.ValidationError(
                'Email ou mot de passe incorrect.', code='authorization'
            )
        attrs['user'] = user
        return attrs


class NewPasswordMixin(serializers.Serializer):
    new_password = serializers.CharField(trim_whitespace=False, write_only=True)
    new_password_confirm = serializers.CharField(trim_whitespace=False, write_only=True)

    def validate_new_passwords(self, attrs, user):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError(
                {'new_password_confirm': 'Les deux mots de passe ne correspondent pas.'}
            )
        try:
            password_validation.validate_password(attrs['new_password'], user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'new_password': list(exc.messages)})


class PasswordChangeSerializer(NewPasswordMixin):
    old_password = serializers.CharField(trim_whitespace=False, write_only=True)

    def validate_old_password(self, value):
        if not self.context['request'].user.check_password(value):
            raise serializers.ValidationError('Mot de passe actuel incorrect.')
        return value

    def validate(self, attrs):
        self.validate_new_passwords(attrs, self.context['request'].user)
        return attrs


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower()


class PasswordResetTokenSerializer(serializers.Serializer):
    """Vérifie le couple (uid, token) reçu dans le lien de réinitialisation."""

    uid = serializers.CharField()
    token = serializers.CharField()

    default_error = 'Lien de réinitialisation invalide ou expiré.'

    def validate(self, attrs):
        try:
            pk = force_str(urlsafe_base64_decode(attrs['uid']))
            user = User.objects.get(pk=pk, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError(self.default_error, code='invalid_link')
        if not default_token_generator.check_token(user, attrs['token']):
            raise serializers.ValidationError(self.default_error, code='invalid_link')
        attrs['user'] = user
        return attrs


class PasswordResetConfirmSerializer(PasswordResetTokenSerializer, NewPasswordMixin):
    def validate(self, attrs):
        attrs = super().validate(attrs)
        self.validate_new_passwords(attrs, attrs['user'])
        return attrs
