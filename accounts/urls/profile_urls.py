from django.urls import path

from ..controllers import profile_controller

# Préfixe : me/
urlpatterns = [
    path('', profile_controller.get_profile, name='me'),
    path('update/', profile_controller.update_profile, name='me-update'),
]
