from django.urls import include, path

from ..controllers import password_controller

# Préfixe : password/reset/
reset_urlpatterns = [
    path('', password_controller.request_password_reset, name='password-reset'),
    path('validate/', password_controller.validate_password_reset, name='password-reset-validate'),
    path('confirm/', password_controller.confirm_password_reset, name='password-reset-confirm'),
]

# Préfixe : password/
urlpatterns = [
    path('change/', password_controller.change_password, name='password-change'),
    path('reset/', include(reset_urlpatterns)),
]
