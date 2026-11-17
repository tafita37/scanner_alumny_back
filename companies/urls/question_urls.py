from django.urls import path

from ..controllers import questionnaire_controller

# Préfixe : questions/ — routes portant sur une question précise du questionnaire adaptatif.
# (Liste et génération des tours d'un audit : voir audit_urls.py.)
urlpatterns = [
    path('<int:pk>/answer/', questionnaire_controller.answer_question, name='question-answer'),
]
