from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Q
from usuarios.models import Role, Profile  # Importar desde la app usuarios
import json

def translate_permission_name(permission_name):
    """Traduce automáticamente los nombres de permisos al español"""
    # Convertir a minúsculas para comparar
    name_lower = permission_name.lower()
    
    # Reemplazos automáticos
    if 'can add' in name_lower:
        return permission_name.replace('Can add', 'Puede agregar').replace('can add', 'Puede agregar')
    elif 'can change' in name_lower:
        return permission_name.replace('Can change', 'Puede modificar').replace('can change', 'Puede modificar')
    elif 'can delete' in name_lower:
        return permission_name.replace('Can delete', 'Puede eliminar').replace('can delete', 'Puede eliminar')
    elif 'can view' in name_lower:
        return permission_name.replace('Can view', 'Puede ver').replace('can view', 'Puede ver')
    else:
        return permission_name

@login_required
def security_dashboard(request):
    """Dashboard principal de seguridad con tabla de roles"""
    # Verificar permisos de administrador
    if not (hasattr(request.user, 'profile') and 
            request.user.profile.role and 
            request.user.profile.role.name == 'administrador'):
        messages.error(request, 'No tienes permisos para acceder a esta sección.')
        return redirect('core:home')
    
    # Estadísticas
    total_roles = Role.objects.count()
    total_permissions = Permission.objects.count()
    total_content_types = ContentType.objects.count()
    
    # Obtener todos los roles para la tabla
    roles = Role.objects.prefetch_related('permissions', 'profile_set').all().order_by('name')
    
    context = {
        'title': 'Seguridad y Accesos',
        'total_roles': total_roles,
        'total_permissions': total_permissions,
        'total_content_types': total_content_types,
        'roles': roles,  # Agregar roles para la tabla
    }
    
    return render(request, 'dashboard.html', context)

@login_required
def role_edit(request, role_id):
    """Editar permisos de un rol existente"""
    # Verificar permisos
    if not (hasattr(request.user, 'profile') and 
            request.user.profile.role and 
            request.user.profile.role.name == 'administrador'):
        messages.error(request, 'No tienes permisos para acceder a esta sección.')
        return redirect('core:home')
    
    role = get_object_or_404(Role, id=role_id)
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                selected_permissions = request.POST.getlist('permissions')
                
                # Actualizar permisos
                if selected_permissions:
                    permissions = Permission.objects.filter(id__in=selected_permissions)
                    role.permissions.set(permissions)
                else:
                    role.permissions.clear()
                
                # Sincronizar permisos de usuarios con este rol
                sync_users_permissions_sync(role.id)
                
                messages.success(request, f'Permisos del rol "{role.name}" actualizados correctamente.')
                return redirect('security:dashboard')
                
        except Exception as e:
            messages.error(request, f'Error al actualizar los permisos: {str(e)}')
    
    # Obtener todos los permisos agrupados por ContentType
    content_types = ContentType.objects.all().order_by('app_label', 'model')
    permissions_by_content_type = {}
    
    for content_type in content_types:
        permissions = Permission.objects.filter(content_type=content_type).order_by('codename')
        if permissions:
            # Crear lista de permisos con nombres traducidos
            permissions_list = []
            for permission in permissions:
                permission_dict = {
                    'id': permission.id,
                    'codename': permission.codename,
                    'name': translate_permission_name(permission.name),
                    'original_name': permission.name,
                }
                permissions_list.append(permission_dict)
            
            permissions_by_content_type[content_type] = permissions_list
    
    # Permisos actuales del rol
    current_permissions = list(role.permissions.values_list('id', flat=True))
    
    context = {
        'title': 'Editar Permisos del Rol',
        'role': role,
        'permissions_by_content_type': permissions_by_content_type,
        'current_permissions': current_permissions,
    }
    
    return render(request, 'role_form.html', context)

@login_required
def permissions_by_content_type_ajax(request):
    """Obtener permisos por tipo de contenido via AJAX"""
    if not (hasattr(request.user, 'profile') and 
            request.user.profile.role and 
            request.user.profile.role.name == 'administrador'):
        return JsonResponse({'success': False, 'error': 'No autorizado'}, status=403)
    
    content_type_id = request.GET.get('content_type_id')
    
    if not content_type_id:
        return JsonResponse({'success': False, 'error': 'ContentType ID requerido'}, status=400)
    
    try:
        content_type = ContentType.objects.get(id=content_type_id)
        permissions = Permission.objects.filter(content_type=content_type).values('id', 'codename', 'name')
        
        return JsonResponse({
            'success': True,
            'permissions': list(permissions),
            'content_type': {
                'id': content_type.id,
                'model': content_type.model,
                'app_label': content_type.app_label,
            }
        })
    except ContentType.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'ContentType no encontrado'}, status=404)

def sync_users_permissions_sync(role_id):
    """Sincronizar permisos de usuarios con un rol específico (versión síncrona)"""
    try:
        role = Role.objects.get(id=role_id)
        profiles = Profile.objects.filter(role=role).select_related('user')
        
        for profile in profiles:
            profile.sync_user_permissions()
            
    except Role.DoesNotExist:
        pass