from django.contrib.auth.models import AbstractUser
from django.db import models

from .user_manager import UserManager


class User(AbstractUser):
    """
    Utilisateur de l'application.

    Hérite de l'utilisateur Django (mot de passe hashé, permissions, groupes,
    is_active, last_login...) mais s'authentifie avec son email au lieu d'un username.
    `first_name` = prénom, `last_name` = nom.
    """

    username = None
    email = models.EmailField('adresse email', unique=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    # Colonnes que to_dict() ne renvoie jamais, même si on les demande.
    HIDDEN_FIELDS = ('password',)

    objects = UserManager()

    class Meta:
        db_table = 'users'
        verbose_name = 'utilisateur'
        verbose_name_plural = 'utilisateurs'
        ordering = ['email']

    def __str__(self):
        return self.email

    def to_dict(self, *fields):
        """
        Colonnes choisies d'un utilisateur déjà chargé (aucune requête SQL).
        Ex. : user.to_dict('id', 'email'). Les HIDDEN_FIELDS sont toujours ignorés.
        """
        return {field: getattr(self, field) for field in fields if field not in self.HIDDEN_FIELDS}

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.lower()
        super().save(*args, **kwargs)
