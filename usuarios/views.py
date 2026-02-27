from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from .forms import CustomUserCreationForm, CustomLoginForm
from .models import Profile, Role
from django.contrib.auth.models import User
import json
from django.db import transaction


def is_admin_or_superuser(user):
    """
    Función auxiliar para verificar si un usuario es administrador o superusuario
    """
    return user.is_superuser or (
        hasattr(user, 'profile') and 
        user.profile.role and 
        user.profile.role.name == 'administrador'
    )


from django.contrib.auth import login

def register_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()  # Esto dispara el signal y crea el perfil automáticamente
            
            # Login automático después del registro
            login(request, user)
            
            # Verificar si hay una invitación pendiente en la sesión
            invitacion_token = request.session.get('invitacion_token')
            if invitacion_token:
                # Limpiar la sesión
                del request.session['invitacion_token']
                if 'invitacion_email' in request.session:
                    del request.session['invitacion_email']
                
                messages.success(request, 'Cuenta creada exitosamente. Procesando tu invitación...')
                # Redirigir a aceptar la invitación
                return redirect('aceptar_invitacion', token=invitacion_token)
            
            messages.success(request, 'Cuenta creada exitosamente. ¡Bienvenido!')
            return redirect('core:home')  # o la página que prefieras
        else:
            # Agregar mensajes de error
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        # Pre-llenar el email si viene de una invitación
        initial_data = {}
        email_from_url = request.GET.get('email')
        email_from_session = request.session.get('invitacion_email')
        
        if email_from_url:
            initial_data['email'] = email_from_url
        elif email_from_session:
            initial_data['email'] = email_from_session
        
        form = CustomUserCreationForm(initial=initial_data)
        
        # Mostrar mensaje informativo si viene de una invitación
        if email_from_url or email_from_session:
            messages.info(request, f'Crea tu cuenta con el email {email_from_url or email_from_session} para aceptar la invitación.')
    
    return render(request, 'register.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        form = CustomLoginForm(request, data=request.POST)
        if form.is_valid():
            email = form.cleaned_data.get('username')  # Viene como 'username' del form
            password = form.cleaned_data.get('password')
            user = authenticate(request, username=email, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f'¡Bienvenido {user.get_full_name()}!')
                return redirect('core:home')  # Actualizado para usar el namespace
            else:
                messages.error(request, 'Credenciales incorrectas.')
        else:
            messages.error(request, 'Por favor corrige los errores del formulario.')
    else:
        form = CustomLoginForm()
    return render(request, 'login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, 'Has cerrado sesión correctamente.')
    return redirect('core:home')  # Actualizado para usar el namespace


@login_required 
def usuarios_list_view(request):
    # Verificar que el usuario sea administrador o superusuario
    if not is_admin_or_superuser(request.user):
        messages.error(request, 'No tienes permisos para acceder a esta sección.')
        return redirect('core:home')
    
    # Parámetros de búsqueda y filtros
    search_query = request.GET.get('search', '').strip()
    role_filter = request.GET.get('role', '').strip()
    page = request.GET.get('page', 1)
    per_page = int(request.GET.get('per_page', 10))
    
    # Query base optimizada con select_related y prefetch_related
    usuarios_query = User.objects.select_related('profile', 'profile__role').all()
    
    # Aplicar filtros de búsqueda si existe término de búsqueda
    if search_query:
        # Buscar por nombre, apellido, username, email
        usuarios_query = usuarios_query.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(profile__first_name__icontains=search_query) |
            Q(profile__last_name__icontains=search_query)
        ).distinct()
    
    # Aplicar filtro por rol si se especifica
    if role_filter:
        if role_filter.lower() == 'sin-rol':
            # Filtrar usuarios sin rol
            usuarios_query = usuarios_query.filter(
                Q(profile__role__isnull=True) |
                Q(profile__isnull=True)
            )
        else:
            # Filtrar por rol específico
            try:
                role_obj = Role.objects.get(name__iexact=role_filter)
                usuarios_query = usuarios_query.filter(profile__role=role_obj)
            except Role.DoesNotExist:
                # Si el rol no existe, devolver queryset vacío
                usuarios_query = usuarios_query.none()
    
    # Ordenar por fecha de registro (más recientes primero)
    usuarios_query = usuarios_query.order_by('-date_joined')
    
    # Obtener el conteo total antes de la paginación
    total_usuarios = usuarios_query.count()
    
    # Paginación
    paginator = Paginator(usuarios_query, per_page)
    
    try:
        usuarios_page = paginator.get_page(page)
    except (PageNotAnInteger, EmptyPage):
        usuarios_page = paginator.get_page(1)
    
    # Obtener roles para el selector
    roles = Role.objects.all().order_by('name')
    
    # Contexto para el template
    context = {
        'usuarios': usuarios_page,
        'roles': roles,
        'title': 'Gestión de Usuarios',
        'search_query': search_query,
        'role_filter': role_filter,
        'total_usuarios': User.objects.count(),  # Total real de usuarios en el sistema
        'filtered_count': total_usuarios,  # Cantidad después de filtros
        'per_page': per_page,
        'paginator': paginator,
    }
    
    # Si es una petición AJAX (para búsqueda en tiempo real)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'html': render(request, 'usuarios_list_partial.html', context).content.decode('utf-8'),
            'total_count': context['total_usuarios'],
            'filtered_count': total_usuarios,
            'shown_count': len(usuarios_page),
            'has_next': usuarios_page.has_next(),
            'has_previous': usuarios_page.has_previous(),
            'current_page': usuarios_page.number,
            'total_pages': paginator.num_pages,
        })
    
    return render(request, 'usuarios_list.html', context)


@login_required
@require_http_methods(["POST"])
@csrf_protect
def delete_user_view(request, user_id):
    # Verificar permisos de administrador o superusuario
    if not is_admin_or_superuser(request.user):
        return JsonResponse({
            'success': False, 
            'error': 'No tienes permisos para realizar esta acción.'
        }, status=403)
    
    try:
        with transaction.atomic():
            user_to_delete = get_object_or_404(User, id=user_id)
            
            # Validaciones de seguridad
            if user_to_delete == request.user:
                return JsonResponse({
                    'success': False, 
                    'error': 'No puedes eliminarte a ti mismo.'
                }, status=400)
            
            # Proteger superusuarios: no permitir eliminarlos
            if user_to_delete.is_superuser:
                return JsonResponse({
                    'success': False,
                    'error': 'No se puede eliminar un superusuario del sistema.'
                }, status=400)
            
            # Verificar si es el único administrador (sin contar superusuarios)
            admin_role = Role.objects.filter(name='administrador').first()
            if (admin_role and hasattr(user_to_delete, 'profile') and user_to_delete.profile.role == admin_role):
                admin_count = User.objects.filter(
                    profile__role=admin_role
                ).exclude(id=user_id).count()
                
                # Contar también superusuarios como administradores
                superuser_count = User.objects.filter(is_superuser=True).exclude(id=user_id).count()
                
                if admin_count == 0 and superuser_count == 0:
                    return JsonResponse({
                        'success': False,
                        'error': 'No puedes eliminar el último administrador del sistema.'
                    }, status=400)
            
            user_name = user_to_delete.get_full_name() or user_to_delete.username
            user_to_delete.delete()
            
            return JsonResponse({
                'success': True, 
                'message': f'Usuario {user_name} eliminado correctamente.'
            })
            
    except User.DoesNotExist:
        return JsonResponse({
            'success': False, 
            'error': 'Usuario no encontrado.'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False, 
            'error': f'Error interno del servidor: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
@csrf_protect
def change_user_role_view(request, user_id):
    # Verificar permisos de administrador o superusuario
    if not is_admin_or_superuser(request.user):
        return JsonResponse({
            'success': False, 
            'error': 'No tienes permisos para realizar esta acción.'
        }, status=403)
    
    try:
        with transaction.atomic():
            # Parsear datos JSON
            try:
                data = json.loads(request.body)
                new_role_id = data.get('role_id')
            except json.JSONDecodeError:
                return JsonResponse({
                    'success': False, 
                    'error': 'Datos inválidos.'
                }, status=400)
            
            if not new_role_id:
                return JsonResponse({
                    'success': False, 
                    'error': 'Rol no especificado.'
                }, status=400)
            
            # Obtener objetos
            user_to_change = get_object_or_404(User, id=user_id)
            new_role = get_object_or_404(Role, id=new_role_id)
            
            # No permitir cambiar roles a superusuarios
            if user_to_change.is_superuser:
                return JsonResponse({
                    'success': False, 
                    'error': 'No se puede cambiar el rol de un superusuario.'
                }, status=400)
            
            # Validaciones de seguridad
            admin_role = Role.objects.filter(name='administrador').first()
            
            # No permitir que se quite a sí mismo el rol de administrador (excepto superusuarios)
            if (user_to_change == request.user and 
                not request.user.is_superuser and
                hasattr(request.user, 'profile') and
                request.user.profile.role == admin_role and 
                new_role != admin_role):
                return JsonResponse({
                    'success': False, 
                    'error': 'No puedes quitarte el rol de administrador a ti mismo.'
                }, status=400)
            
            # Verificar que no sea el último administrador
            if (hasattr(user_to_change, 'profile') and 
                user_to_change.profile.role == admin_role and 
                new_role != admin_role):
                admin_count = User.objects.filter(profile__role=admin_role).count()
                superuser_count = User.objects.filter(is_superuser=True).count()
                
                # Si hay superusuarios, siempre hay al menos un "administrador" en el sistema
                if admin_count <= 1 and superuser_count == 0:
                    return JsonResponse({
                        'success': False,
                        'error': 'No puedes quitar el rol de administrador al último administrador del sistema.'
                    }, status=400)
            
            # Actualizar el rol
            if hasattr(user_to_change, 'profile'):
                old_role = user_to_change.profile.role
                user_to_change.profile.role = new_role
                user_to_change.profile.save()
            else:
                # Crear perfil si no existe (caso edge)
                Profile.objects.create(user=user_to_change, role=new_role)
                old_role = None
            
            user_name = user_to_change.get_full_name() or user_to_change.username
            
            return JsonResponse({
                'success': True,
                'message': f'Rol de {user_name} actualizado de {old_role.name if old_role else "sin rol"} a {new_role.name}.',
                'user_id': user_id,
                'new_role': {
                    'id': new_role.id,
                    'name': new_role.name
                }
            })
            
    except User.DoesNotExist:
        return JsonResponse({
            'success': False, 
            'error': 'Usuario no encontrado.'
        }, status=404)
    except Role.DoesNotExist:
        return JsonResponse({
            'success': False, 
            'error': 'Rol no encontrado.'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False, 
            'error': f'Error interno del servidor: {str(e)}'
        }, status=500)


@login_required
def search_users_ajax(request):
    """Vista AJAX optimizada para búsqueda de usuarios en tiempo real"""
    if not is_admin_or_superuser(request.user):
        return JsonResponse({
            'success': False, 
            'error': 'No tienes permisos.'
        }, status=403)
    
    search_query = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '').strip()
    page = int(request.GET.get('page', 1))
    per_page = int(request.GET.get('per_page', 10))
    
    # Query optimizada
    usuarios_query = User.objects.select_related('profile', 'profile__role')
    
    # Aplicar filtros de búsqueda
    if search_query:
        usuarios_query = usuarios_query.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(profile__first_name__icontains=search_query) |
            Q(profile__last_name__icontains=search_query)
        ).distinct()
    
    # Aplicar filtro por rol
    if role_filter:
        if role_filter.lower() == 'sin-rol':
            usuarios_query = usuarios_query.filter(
                Q(profile__role__isnull=True) |
                Q(profile__isnull=True)
            )
        else:
            try:
                role_obj = Role.objects.get(name__iexact=role_filter)
                usuarios_query = usuarios_query.filter(profile__role=role_obj)
            except Role.DoesNotExist:
                usuarios_query = usuarios_query.none()
    
    usuarios_query = usuarios_query.order_by('-date_joined')
    
    # Paginación
    paginator = Paginator(usuarios_query, per_page)
    usuarios_page = paginator.get_page(page)
    
    # Preparar datos para JSON
    usuarios_data = []
    for usuario in usuarios_page:
        # Determinar el rol a mostrar
        if usuario.is_superuser:
            role_data = {
                'id': None,
                'name': 'Superusuario',
            }
        elif hasattr(usuario, 'profile') and usuario.profile.role:
            role_data = {
                'id': usuario.profile.role.id,
                'name': usuario.profile.role.name,
            }
        else:
            role_data = {
                'id': None,
                'name': 'Sin rol',
            }
        
        usuarios_data.append({
            'id': usuario.id,
            'username': usuario.username,
            'email': usuario.email,
            'first_name': usuario.first_name,
            'last_name': usuario.last_name,
            'full_name': usuario.get_full_name(),
            'date_joined': usuario.date_joined.strftime('%d/%m/%Y'),
            'role': role_data,
            'is_current_user': usuario == request.user,
            'is_superuser': usuario.is_superuser,
        })
    
    return JsonResponse({
        'success': True,
        'users': usuarios_data,
        'pagination': {
            'current_page': usuarios_page.number,
            'total_pages': paginator.num_pages,
            'has_next': usuarios_page.has_next(),
            'has_previous': usuarios_page.has_previous(),
            'total_count': paginator.count,
            'start_index': usuarios_page.start_index(),
            'end_index': usuarios_page.end_index(),
        }
    })


@login_required 
def seguridad_accesos_view(request):
    # Verificar que el usuario sea administrador o superusuario
    if not is_admin_or_superuser(request.user):
        messages.error(request, 'No tienes permisos para acceder a esta sección.')
        return redirect('core:home')
    
    context = {
        'title': 'Seguridad y Accesos',
        'message': 'Esta sección estará disponible próximamente.'
    }
    
    return render(request, 'usuarios/seguridad_accesos.html', context)


@login_required
def dashboard(request):
    # Redirección directa para invitados a la página principal
    if hasattr(request.user, 'profile') and request.user.profile.role and request.user.profile.role.name == 'invitado':
        return redirect('core:home')
    context = {
        'title': 'Dashboard',
        'message': 'Bienvenido al dashboard.'
    }
    return render(request, 'dashboard.html', context)