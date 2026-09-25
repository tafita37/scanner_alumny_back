from django.urls import path

from ..controllers import auth_controller

urlpatterns = [
    path('login/', auth_controller.login, name='login'),
    path('logout/', auth_controller.logout, name='logout'),
    path('token/refresh/', auth_controller.refresh_token, name='token-refresh'),
]
