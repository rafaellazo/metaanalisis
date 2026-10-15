# pymetanalis/context_processors.py

from pymetanalis.models import UsuarioProyecto
from django.core.cache import cache

def user_project_roles(request):
    """
    Context processor que añade información sobre los roles del usuario en proyectos
    """
    context = {
        'is_project_owner': False,
        'is_project_supervisor': False,
        'is_project_collaborator': False,
        'user_projects': [],
        'owned_projects': [],
        'supervised_projects': [],
        'collaborated_projects': [],
        'has_any_project_role': False,
        'can_create_projects': False,
    }
    
    if request.user.is_authenticated:
        # Obtener todos los proyectos del usuario
        user_projects = UsuarioProyecto.objects.filter(
            usuario=request.user
        ).select_related('proyecto')
        
        context['user_projects'] = user_projects
        context['has_any_project_role'] = user_projects.exists()
        
        # Separar proyectos por rol
        context['owned_projects'] = user_projects.filter(rol_proyecto='DUEÑO')
        context['supervised_projects'] = user_projects.filter(rol_proyecto='SUPERVISOR')
        context['collaborated_projects'] = user_projects.filter(rol_proyecto='COLABORADOR')
        
        # Verificar si tiene alguno de estos roles en algún proyecto
        context['is_project_owner'] = context['owned_projects'].exists()
        context['is_project_supervisor'] = context['supervised_projects'].exists()
        context['is_project_collaborator'] = context['collaborated_projects'].exists()
        
        # Determinar si puede crear proyectos
        # Solo investigadores y administradores pueden crear proyectos
        if hasattr(request.user, 'profile') and request.user.profile.role:
            role_name = request.user.profile.role.name
            context['can_create_projects'] = (
                request.user.is_superuser or 
                role_name in ['administrador', 'investigador']
            )
    
    return context


def saldo_consumo_ia(request):
    context = {'saldo_consumo': None}
    if not request.user.is_authenticated:
        return context
    role = getattr(getattr(request.user, 'profile', None), 'role', None)
    if not (request.user.is_superuser or (role and role.name == 'administrador')):
        return context
    key = f'saldo_consumo_ia:{request.user.pk}'
    cached = cache.get(key)
    if cached is None:
        from articulos.servicios_saldo import estado_saldo, porcentaje_restante, saldo_actual
        saldo = saldo_actual()
        cached = {'saldo': saldo, 'porcentaje': porcentaje_restante(),
                  'estado': estado_saldo()}
        cache.set(key, cached, 15)
    context['saldo_consumo'] = cached
    return context