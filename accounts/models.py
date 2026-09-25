"""
Point d'entrée des modèles de l'app : Django découvre les modèles via ce fichier.
Chaque métier est défini dans son propre fichier du dossier `metier/`.
"""
from .metier.user import User
from .metier.user_manager import UserManager

__all__ = ['User', 'UserManager']
