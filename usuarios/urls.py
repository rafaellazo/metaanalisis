# usuarios/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('list/', views.usuarios_list_view, name='usuarios_list'),
    path('delete/<int:user_id>/', views.delete_user_view, name='delete_user'),
    path('change-role/<int:user_id>/', views.change_user_role_view, name='change_user_role'),
    path('seguridad-accesos/', views.seguridad_accesos_view, name='seguridad_accesos'),
    #path('invitado/', views.proyectos_view, name='proyectos')
]