from django.urls import path

from ..controllers import crud_controller

# Préfixe : (racine de /api/companies/) — un groupe de routes par ressource de CRUD_RESOURCES.
# Ex. pour 'industries' : industries/, industries/<pk>/, industries/create/,
# industries/<pk>/update/, industries/<pk>/delete/
urlpatterns = []

for resource in crud_controller.CRUD_RESOURCES:
    kwargs = {'resource': resource}
    urlpatterns += [
        path(f'{resource}/', crud_controller.list_objects, kwargs, name=f'{resource}-list'),
        path(f'{resource}/create/', crud_controller.create_object, kwargs, name=f'{resource}-create'),
        path(f'{resource}/<int:pk>/', crud_controller.get_object, kwargs, name=f'{resource}-detail'),
        path(f'{resource}/<int:pk>/update/', crud_controller.update_object, kwargs, name=f'{resource}-update'),
        path(f'{resource}/<int:pk>/delete/', crud_controller.delete_object, kwargs, name=f'{resource}-delete'),
    ]
