from django.urls import path
from . import views

app_name = 'security'

urlpatterns = [
    # Dashboard principal (incluye tabla de roles)
    path('', views.security_dashboard, name='dashboard'),
    
    # Gestión de roles
    path('roles/<int:role_id>/edit/', views.role_edit, name='role_edit'),
    
    # AJAX endpoints
    path('api/permissions-by-content-type/', views.permissions_by_content_type_ajax, name='permissions_by_content_type'),
]