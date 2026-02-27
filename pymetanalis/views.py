from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.utils import timezone
from django.utils.crypto import get_random_string
from .models import Proyecto, UsuarioProyecto, SolicitudProyecto, Notificacion, Invitacion
import json
import datetime
from pymetanalis.models import Proyecto, UsuarioProyecto
from articulos.models import CampoMetanalisis, PlantillaBusqueda, AsignacionCampo
from itertools import groupby
import logging

logger = logging.getLogger(__name__)

# ==================== FUNCIÓN HELPER ====================

def crear_notificacion(usuario, tipo, titulo, mensaje, url=None, proyecto=None, solicitud=None):
    """Función helper para crear notificaciones de forma segura"""
    try:
        notificacion = Notificacion.objects.create(
            usuario=usuario,
            tipo=tipo,
            titulo=titulo,
            mensaje=mensaje,
            url=url,
            proyecto=proyecto,
            solicitud=solicitud
        )
        logger.info(f"✅ Notificación creada: {titulo} para {usuario.username}")
        return notificacion
    except Exception as e:
        logger.error(f"❌ Error creando notificación para {usuario.username}: {e}")
        return None


# ==================== GESTIÓN DE PROYECTOS ====================
@login_required
def crear_proyecto(request):
    """Vista para crear un nuevo proyecto CON plantilla obligatoria"""
    
    # Verificar permisos
    puede_crear = False
    if request.user.is_superuser:
        puede_crear = True
    elif hasattr(request.user, 'profile') and request.user.profile.role:
        puede_crear = request.user.profile.role.name in ['administrador', 'investigador']
    
    if not puede_crear:
        messages.error(request, 'No tienes permisos para crear proyectos. Solicita el rol de Investigador.')
        return redirect('core:home')
    
    from articulos.models import CampoMetanalisis, PlantillaBusqueda
    from itertools import groupby
    from operator import attrgetter
    
    # 🌍 OBTENER VARIABLES GLOBALES (sin proyecto asignado)
    variables_globales = CampoMetanalisis.objects.filter(
        proyecto__isnull=True,
        activo=True
    ).order_by('categoria', 'nombre')
    
    # 👥 OBTENER VARIABLES COMUNITARIAS (de otros proyectos)
    variables_comunitarias = CampoMetanalisis.objects.filter(
        proyecto__isnull=False,
        activo=True
    ).select_related('proyecto', 'creado_por').order_by('categoria', 'nombre')
    
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        categoria = request.POST.get('categoria', 'SALUD')
        descripcion = request.POST.get('descripcion', '').strip()
        campos_ids = request.POST.getlist('campos')  # IDs de campos seleccionados
        
        # Validaciones
        if not nombre:
            messages.error(request, 'El nombre del proyecto es obligatorio.')
            return render(request, 'crear_proyectos.html', {
                'categorias': Proyecto.CATEGORIA_CHOICES,
                'variables_globales_agrupadas': agrupar_variables(variables_globales),
                'variables_comunitarias_agrupadas': agrupar_variables(variables_comunitarias),
                'total_globales': variables_globales.count(),
                'total_comunitarias': variables_comunitarias.count(),
            })
        
        # Validar que seleccionó al menos un campo
        if not campos_ids:
            messages.error(request, 'Debes seleccionar al menos un campo para la plantilla del proyecto.')
            return render(request, 'crear_proyectos.html', {
                'categorias': Proyecto.CATEGORIA_CHOICES,
                'variables_globales_agrupadas': agrupar_variables(variables_globales),
                'variables_comunitarias_agrupadas': agrupar_variables(variables_comunitarias),
                'total_globales': variables_globales.count(),
                'total_comunitarias': variables_comunitarias.count(),
                'nombre': nombre,
                'descripcion': descripcion,
                'categoria': categoria
            })
        
        if len(nombre) > 255:
            messages.error(request, 'El nombre del proyecto es demasiado largo (máximo 255 caracteres).')
            return render(request, 'crear_proyectos.html', {
                'categorias': Proyecto.CATEGORIA_CHOICES,
                'variables_globales_agrupadas': agrupar_variables(variables_globales),
                'variables_comunitarias_agrupadas': agrupar_variables(variables_comunitarias),
                'total_globales': variables_globales.count(),
                'total_comunitarias': variables_comunitarias.count(),
            })
        
        configuracion_json = {}
        if descripcion:
            configuracion_json['descripcion'] = descripcion
        
        try:
            with transaction.atomic():
                # Crear el proyecto
                proyecto = Proyecto.objects.create(
                    nombre=nombre,
                    categoria=categoria,
                    usuario_creador=request.user,
                    estado='ACTIVO',
                    configuracion=configuracion_json
                )
                
                # Asignar al creador como DUEÑO
                UsuarioProyecto.objects.create(
                    usuario=request.user,
                    proyecto=proyecto,
                    rol_proyecto='DUEÑO',
                    puede_invitar=True
                )
                
                # Crear plantilla automáticamente
                plantilla = PlantillaBusqueda.objects.create(
                    nombre=f'Plantilla {proyecto.nombre}',
                    descripcion='Plantilla principal del proyecto',
                    proyecto=proyecto,
                    creado_por=request.user,
                    es_predeterminada=True
                )
                
                # Asignar campos seleccionados (globales y comunitarios)
                campos = CampoMetanalisis.objects.filter(id__in=campos_ids, activo=True)
                plantilla.campos.set(campos)
                
                # Contar cuántos son globales y cuántos comunitarios
                globales_count = campos.filter(proyecto__isnull=True).count()
                comunitarios_count = campos.filter(proyecto__isnull=False).count()
                
                mensaje = f'✅ Proyecto "{proyecto.nombre}" creado con {campos.count()} campos en la plantilla'
                if globales_count > 0 and comunitarios_count > 0:
                    mensaje += f' ({globales_count} globales, {comunitarios_count} comunitarios).'
                elif globales_count > 0:
                    mensaje += f' ({globales_count} globales).'
                elif comunitarios_count > 0:
                    mensaje += f' ({comunitarios_count} comunitarios).'
                else:
                    mensaje += '.'
                
                messages.success(request, mensaje)
                return redirect('detalle_proyecto', proyecto_id=proyecto.id)
                
        except Exception as e:
            messages.error(request, f'Error al crear el proyecto: {str(e)}')
    
    # GET: Mostrar formulario
    # Función helper para agrupar variables
    def agrupar_variables(queryset):
        """Agrupa variables por categoría"""
        variables_agrupadas = {}
        for categoria_key, items in groupby(queryset, key=attrgetter('categoria')):
            categoria_nombre = dict(CampoMetanalisis.CATEGORIA_CHOICES).get(categoria_key, categoria_key)
            items_list = list(items)
            
            items_con_info = []
            for campo in items_list:
                items_con_info.append({
                    'campo': campo,
                    'es_global': campo.proyecto is None,
                    'proyecto_origen': campo.proyecto.nombre if campo.proyecto else None,
                    'creado_por_nombre': campo.creado_por.get_full_name() if campo.creado_por else 'Sistema'
                })
            
            if items_con_info:
                variables_agrupadas[categoria_nombre] = items_con_info
        
        return variables_agrupadas
    
    context = {
        'categorias': Proyecto.CATEGORIA_CHOICES,
        'variables_globales_agrupadas': agrupar_variables(variables_globales),
        'variables_comunitarias_agrupadas': agrupar_variables(variables_comunitarias),
        'total_globales': variables_globales.count(),
        'total_comunitarias': variables_comunitarias.count(),
        'categorias_campos': CampoMetanalisis.CATEGORIA_CHOICES,
    }
    
    return render(request, 'crear_proyectos.html', context)

@login_required
def mis_proyectos(request):
    """Vista para listar los proyectos del usuario"""
    
    # Importar modelo de Articulo
    from articulos.models import Articulo
    
    # Obtener proyectos donde el usuario participa
    usuario_proyectos = UsuarioProyecto.objects.filter(
        usuario=request.user
    ).select_related('proyecto').order_by('-fecha_incorporacion')
    
    # Filtros
    filtro_rol = request.GET.get('rol', '')
    filtro_estado = request.GET.get('estado', '')
    filtro_categoria = request.GET.get('categoria', '')
    busqueda = request.GET.get('q', '')
    
    if filtro_rol:
        usuario_proyectos = usuario_proyectos.filter(rol_proyecto=filtro_rol)
    
    proyectos_ids = usuario_proyectos.values_list('proyecto_id', flat=True)
    proyectos = Proyecto.objects.filter(id__in=proyectos_ids)
    
    if filtro_estado:
        proyectos = proyectos.filter(estado=filtro_estado)
    
    if filtro_categoria:
        proyectos = proyectos.filter(categoria=filtro_categoria)
    
    if busqueda:
        proyectos = proyectos.filter(
            Q(nombre__icontains=busqueda) |
            Q(usuario_creador__username__icontains=busqueda) |
            Q(usuario_creador__first_name__icontains=busqueda) |
            Q(usuario_creador__last_name__icontains=busqueda)
        )
    
    # Agregar información del rol del usuario en cada proyecto
    proyectos_data = []
    for proyecto in proyectos:
        usuario_proyecto = usuario_proyectos.filter(proyecto=proyecto).first()
        
        # CALCULAR PROGRESO REAL DESDE LA BASE DE DATOS DE ARTÍCULOS
        total_articulos = Articulo.objects.filter(proyecto=proyecto).count()
        
        # Artículos "trabajados" son los que NO están en EN_ESPERA ni PENDIENTE
        articulos_trabajados = Articulo.objects.filter(
            proyecto=proyecto
        ).exclude(
            estado__in=['EN_ESPERA', 'PENDIENTE']
        ).count()
        
        # Calcular progreso
        progreso = 0
        if total_articulos > 0:
            progreso = round((articulos_trabajados / total_articulos) * 100, 1)
        
        proyectos_data.append({
            'proyecto': proyecto,
            'rol': usuario_proyecto.rol_proyecto if usuario_proyecto else None,
            'puede_invitar': usuario_proyecto.puede_invitar if usuario_proyecto else False,
            'progreso': progreso,
            'total_articulos': total_articulos,
            'articulos_trabajados': articulos_trabajados
        })
    
    # Paginación
    paginator = Paginator(proyectos_data, 9)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'filtro_rol': filtro_rol,
        'filtro_estado': filtro_estado,
        'filtro_categoria': filtro_categoria,
        'busqueda': busqueda,
        'roles': UsuarioProyecto.ROL_PROYECTO_CHOICES,
        'estados': Proyecto.ESTADO_CHOICES,
        'categorias': Proyecto.CATEGORIA_CHOICES,
    }
    
    return render(request, 'mis_proyectos.html', context)

@login_required
def detalle_proyecto(request, proyecto_id):
    """Vista para ver los detalles de un proyecto"""
    
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    
    # Verificar que el usuario tiene acceso al proyecto
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto
    ).first()
    
    es_admin = request.user.is_superuser or (
        hasattr(request.user, 'profile') and 
        request.user.profile.role and 
        request.user.profile.role.name == 'administrador'
    )
    
    if not usuario_proyecto and not es_admin:
        messages.error(request, 'No tienes acceso a este proyecto.')
        return redirect('mis_proyectos')
    
    # Guardar proyecto seleccionado en sesión
    request.session['proyecto_seleccionado'] = {
        'id': proyecto.id,
        'nombre': proyecto.nombre,
        'rol': usuario_proyecto.rol_proyecto if usuario_proyecto else 'ADMIN'
    }
    request.session.modified = True
    
    # Obtener miembros del proyecto
    miembros = UsuarioProyecto.objects.filter(
        proyecto=proyecto
    ).select_related('usuario', 'usuario__profile').order_by('-fecha_incorporacion')
    
    #CALCULAR PROGRESO REAL DESDE LA BASE DE DATOS DE ARTÍCULOS
    from articulos.models import Articulo
    
    # Contar artículos por estado
    total_articulos = Articulo.objects.filter(proyecto=proyecto).count()
    
    # Artículos "trabajados" son los que NO están en EN_ESPERA ni PENDIENTE
    articulos_trabajados = Articulo.objects.filter(
        proyecto=proyecto
    ).exclude(
        estado__in=['EN_ESPERA', 'PENDIENTE']
    ).count()
    
    # Calcular progreso
    progreso = 0
    if total_articulos > 0:
        progreso = round((articulos_trabajados / total_articulos) * 100, 1)
    
    #ESTADÍSTICAS DETALLADAS POR ESTADO
    articulos_por_estado = {
        'en_espera': Articulo.objects.filter(proyecto=proyecto, estado='EN_ESPERA').count(),
        'pendientes': Articulo.objects.filter(proyecto=proyecto, estado='PENDIENTE').count(),
        'en_proceso': Articulo.objects.filter(proyecto=proyecto, estado='EN_PROCESO').count(),
        'en_revision': Articulo.objects.filter(proyecto=proyecto, estado='EN_REVISION').count(),
        'aprobados': Articulo.objects.filter(proyecto=proyecto, estado='APROBADO').count(),
    }
    
    # Obtener solicitudes pendientes si es dueño o supervisor
    solicitudes_pendientes = None
    if usuario_proyecto and usuario_proyecto.rol_proyecto in ['DUEÑO', 'SUPERVISOR']:
        solicitudes_pendientes = SolicitudProyecto.objects.filter(
            proyecto=proyecto,
            estado='PENDIENTE'
        ).select_related('usuario').order_by('-fecha_solicitud')
    
    # Definir opciones de menú según el rol
    opciones_menu = {}
    
    if usuario_proyecto:
        rol = usuario_proyecto.rol_proyecto
        
        # COLABORADOR: Opciones básicas
        if rol == 'COLABORADOR':
            opciones_menu = {
                'mis_articulos': {
                    'titulo': 'Mis Artículos',
                    'icono': 'document',
                    'opciones': [
                        {
                            'nombre': 'Visualizar Artículos',
                            'url': reverse('articulos:ver_articulos', args=[proyecto.id]),
                            'icono': 'eye',
                            'activo': True
                        },
                        {
                            'nombre': 'Subir Archivos .bib',
                            'url': reverse('articulos:subir_archivo', args=[proyecto.id]),
                            'icono': 'upload',
                            'activo': True
                        }
                    ]
                },
                'mi_progreso': {
                    'titulo': 'Mi Progreso',
                    'icono': 'chart',
                    'opciones': [
                        {
                            'nombre': 'Estadísticas Personales',
                            'url': reverse('articulos:mi_progreso', args=[proyecto.id]),
                            'icono': 'trending-up',
                            'activo': True
                        }
                    ]
                }
                ,
                'meta_analisis': {
                    'titulo': 'Meta analisis',
                    'icono': 'analysis',
                    'opciones': [
                        {
                            'nombre': 'Descargar el excel del proyecto',
                            'url': reverse('articulos:generar_excel_proyecto', args=[proyecto.id]),
                            'icono': 'download',
                            'activo': False
                        },
                        {
                            'nombre': 'Panel de Control Forest Plot',
                            'url': reverse('articulos:panel_forest_plot', args=[proyecto.id]),
                            'icono': 'bar-chart',
                            'activo': True
                        }
                    ]
                },
                'componentes_principales': {
                    'titulo': 'Componentes Principales',
                    'icono': 'scatter-plot',
                    'opciones': [
                        {
                            'nombre': 'Análisis PCA',
                            'url': reverse('articulos:panel_pca', args=[proyecto.id]),
                            'icono': 'analytics',
                            'activo': True
                        }
                    ]
                }
            }
        
        # SUPERVISOR: Colaborador + Supervisión
        elif rol == 'SUPERVISOR':
            opciones_menu = {
                'mis_articulos': {
                    'titulo': 'Mis Artículos',
                    'icono': 'document',
                    'opciones': [
                        {
                            'nombre': 'Visualizar Artículos',
                            'url': reverse('articulos:ver_articulos', args=[proyecto.id]),
                            'icono': 'eye',
                            'activo': True
                        },
                        {
                            'nombre': 'Subir Archivos .bib',
                            'url': reverse('articulos:subir_archivo', args=[proyecto.id]),
                            'icono': 'upload',
                            'activo': True
                        }
                    ]
                },
                'mi_progreso': {
                    'titulo': 'Mi Progreso',
                    'icono': 'chart',
                    'opciones': [
                        {
                            'nombre': 'Estadísticas Personales',
                            'url': reverse('articulos:mi_progreso', args=[proyecto.id]),
                            'icono': 'trending-up',
                            'activo': True
                        }
                    ]
                },
                'supervision': {
                    'titulo': 'Supervisión',
                    'icono': 'clipboard-check',
                    'opciones': [
                        {
                            'nombre': 'Bandeja de Revisión',
                            'url': reverse('articulos:bandeja_revision', args=[proyecto.id]),
                            'icono': 'inbox',
                            'activo': True
                        }
                    ]
                },
                'analisis': {
                    'titulo': 'Análisis',
                    'icono': 'bar-chart',
                    'opciones': [
                        {
                            'nombre': 'Estadísticas del Proyecto',
                            'url': reverse('articulos:estadisticas_proyecto', args=[proyecto.id]),
                            'icono': 'pie-chart',
                            'activo': True
                        }
                    ]
                }
                ,
                'meta_analisis': {
                    'titulo': 'Meta analisis',
                    'icono': 'analysis',
                    'opciones': [
                        {
                            'nombre': 'Descargar el excel del proyecto',
                            'url': reverse('articulos:generar_excel_proyecto', args=[proyecto.id]),
                            'icono': 'download',
                            'activo': True
                        },
                        {
                            'nombre': 'Panel de Control Forest Plot',
                            'url': reverse('articulos:panel_forest_plot', args=[proyecto.id]),
                            'icono': 'bar-chart',
                            'activo': True
                        }
                    ]
                },
                'componentes_principales': {
                    'titulo': 'Componentes Principales',
                    'icono': 'scatter-plot',
                    'opciones': [
                        {
                            'nombre': 'Análisis PCA',
                            'url': reverse('articulos:panel_pca', args=[proyecto.id]),
                            'icono': 'analytics',
                            'activo': True
                        }
                    ]
                }
            }
        
        # DUEÑO: Todo lo anterior + Gestión de Tareas
        elif rol == 'DUEÑO':
            opciones_menu = {
                'configuracion': {
                    'titulo': 'Configuración',
                    'icono': 'settings',
                    'opciones': [
                        {
                            'nombre': 'Gestionar Variables',
                            'url': reverse('articulos:gestionar_variables_globales', args=[proyecto.id]),
                            'icono': 'database',
                            'descripcion': 'Crear nuevas variables del sistema o del proyecto',
                            'activo': True 
                        },
                        {
                            'nombre': 'Editar Plantilla',
                            'url': reverse('articulos:editar_plantilla_proyecto', args=[proyecto.id]),
                            'icono': 'sliders',
                            'descripcion': 'Personalizar campos de la plantilla del proyecto',
                            'activo': True  
                        }
                    ]
                },
                'mis_articulos': {
                    'titulo': 'Mis Artículos',
                    'icono': 'document',
                    'opciones': [
                        {
                            'nombre': 'Visualizar Artículos',
                            'url': reverse('articulos:ver_articulos', args=[proyecto.id]),
                            'icono': 'eye',
                            'activo': True
                        },
                        {
                            'nombre': 'Subir Archivos .bib',
                            'url': reverse('articulos:subir_archivo', args=[proyecto.id]),
                            'icono': 'upload',
                            'activo': True
                        }
                    ]
                },
                'mi_progreso': {
                    'titulo': 'Mi Progreso',
                    'icono': 'chart',
                    'opciones': [
                        {
                            'nombre': 'Estadísticas Personales',
                            'url': reverse('articulos:mi_progreso', args=[proyecto.id]),
                            'icono': 'trending-up',
                            'activo': True
                        }
                    ]
                },
                'supervision': {
                    'titulo': 'Supervisión',
                    'icono': 'clipboard-check',
                    'opciones': [
                        {
                            'nombre': 'Bandeja de Revisión',
                            'url': reverse('articulos:bandeja_revision', args=[proyecto.id]),
                            'icono': 'inbox',
                            'activo': True
                        }
                    ]
                },
                'gestion_equipo': {
                    'titulo': 'Gestión de Equipo',
                    'icono': 'users',
                    'opciones': [
                        {
                            'nombre': 'Invitar Usuario',
                            'url': reverse('invitar_usuario', args=[proyecto.id]),
                            'icono': 'user-plus',
                            'activo': True
                        }
                    ]
                },
                'analisis': {
                    'titulo': 'Análisis',
                    'icono': 'bar-chart',
                    'opciones': [
                        {
                            'nombre': 'Estadísticas del Proyecto',
                            'url': reverse('articulos:estadisticas_proyecto', args=[proyecto.id]),
                            'icono': 'pie-chart',
                            'activo': True
                        },
                        {
                            'nombre': 'Estadísticas por Usuario',
                            'url': reverse('articulos:estadisticas_por_usuario', args=[proyecto.id]),
                            'icono': 'users',
                            'activo': True
                        }
                    ]
                }
                ,
                'meta_analisis': {
                    'titulo': 'Meta analisis',
                    'icono': 'analysis',
                    'opciones': [
                        {
                            'nombre': 'Descargar el excel del proyecto',
                            'url': reverse('articulos:generar_excel_proyecto', args=[proyecto.id]),
                            'icono': 'download',
                            'activo': True
                        },
                        {
                            'nombre': 'Panel de Control Forest Plot',
                            'url': reverse('articulos:panel_forest_plot', args=[proyecto.id]),
                            'icono': 'bar-chart',
                            'activo': True
                        }
                    ]
                },
                'componentes_principales': {
                    'titulo': 'Componentes Principales',
                    'icono': 'scatter-plot',
                    'opciones': [
                        {
                            'nombre': 'Análisis PCA',
                            'url': reverse('articulos:panel_pca', args=[proyecto.id]),
                            'icono': 'analytics',
                            'activo': True
                        }
                    ]
                }
            }
    
    context = {
        'proyecto': proyecto,
        'usuario_proyecto': usuario_proyecto,
        'miembros': miembros,
        'progreso': progreso,
        'total_articulos': total_articulos,
        'articulos_trabajados': articulos_trabajados,
        'articulos_restantes': total_articulos - articulos_trabajados,
        'articulos_por_estado': articulos_por_estado,
        'solicitudes_pendientes': solicitudes_pendientes,
        'es_dueno': usuario_proyecto and usuario_proyecto.rol_proyecto == 'DUEÑO',
        'es_supervisor': usuario_proyecto and usuario_proyecto.rol_proyecto == 'SUPERVISOR',
        'es_colaborador': usuario_proyecto and usuario_proyecto.rol_proyecto == 'COLABORADOR',
        'puede_gestionar': (usuario_proyecto and usuario_proyecto.rol_proyecto in ['DUEÑO', 'SUPERVISOR']) or es_admin,
        'opciones_menu': opciones_menu,
        
    }
    
    return render(request, 'detalle_proyecto.html', context)

@login_required
def buscar_proyectos(request):
    """Vista para buscar proyectos públicos"""
    
    busqueda = request.GET.get('q', '')
    categoria = request.GET.get('categoria', '')
    
    # Obtener todos los proyectos activos
    proyectos = Proyecto.objects.filter(estado='ACTIVO').select_related('usuario_creador')
    
    if busqueda:
        proyectos = proyectos.filter(
            Q(nombre__icontains=busqueda) |
            Q(usuario_creador__username__icontains=busqueda) |
            Q(usuario_creador__first_name__icontains=busqueda)
        )
    
    if categoria:
        proyectos = proyectos.filter(categoria=categoria)
    
    # Anotar con el número de miembros
    proyectos = proyectos.annotate(num_miembros=Count('usuario_proyectos'))
    
    # Marcar proyectos donde el usuario ya participa
    mis_proyectos_ids = UsuarioProyecto.objects.filter(
        usuario=request.user
    ).values_list('proyecto_id', flat=True)
    
    proyectos_data = []
    for proyecto in proyectos:
        proyectos_data.append({
            'proyecto': proyecto,
            'ya_participo': proyecto.id in mis_proyectos_ids,
            'num_miembros': proyecto.num_miembros,
        })
    
    # Paginación
    paginator = Paginator(proyectos_data, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'busqueda': busqueda,
        'categoria_filtro': categoria,
        'categorias': Proyecto.CATEGORIA_CHOICES,
    }
    
    return render(request, 'buscar_proyectos.html', context)

@login_required
def editar_proyecto(request, proyecto_id):
    """Vista para editar un proyecto (solo dueños)"""
    
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    
    # Verificar permisos
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto,
        rol_proyecto='DUEÑO'
    ).first()
    
    if not usuario_proyecto and not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para editar este proyecto.')
        return redirect('detalle_proyecto', proyecto_id=proyecto_id)
    
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        categoria = request.POST.get('categoria')
        estado = request.POST.get('estado')
        descripcion = request.POST.get('descripcion', '').strip()
        
        if not nombre:
            messages.error(request, 'El nombre del proyecto es obligatorio.')
        else:
            proyecto.nombre = nombre
            proyecto.categoria = categoria
            proyecto.estado = estado
            
            # Actualizar configuración
            if not proyecto.configuracion:
                proyecto.configuracion = {}
            proyecto.configuracion['descripcion'] = descripcion
            
            proyecto.save()
            messages.success(request, 'Proyecto actualizado exitosamente.')
            return redirect('detalle_proyecto', proyecto_id=proyecto_id)
    
    return render(request, 'editar_proyecto.html', {
        'proyecto': proyecto,
        'categorias': Proyecto.CATEGORIA_CHOICES,
        'estados': Proyecto.ESTADO_CHOICES,
        'es_dueno': usuario_proyecto is not None,
    })


@login_required
@require_POST
def eliminar_proyecto(request, proyecto_id):
    """Vista para eliminar un proyecto (solo dueños)"""
    
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    
    # Verificar permisos - solo el dueño puede eliminar
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto,
        rol_proyecto='DUEÑO'
    ).first()
    
    if not usuario_proyecto and not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para eliminar este proyecto.')
        return redirect('detalle_proyecto', proyecto_id=proyecto_id)
    
    try:
        with transaction.atomic():
            nombre_proyecto = proyecto.nombre
            # Eliminar el proyecto (Django se encarga de las relaciones CASCADE)
            proyecto.delete()
            
            messages.success(request, f'Proyecto "{nombre_proyecto}" eliminado exitosamente.')
            return redirect('mis_proyectos')
            
    except Exception as e:
        logger.error(f"Error eliminando proyecto {proyecto_id}: {e}")
        messages.error(request, f'Error al eliminar el proyecto: {str(e)}')
        return redirect('detalle_proyecto', proyecto_id=proyecto_id)


from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from .models import Proyecto, UsuarioProyecto, Invitacion
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
import logging

logger = logging.getLogger(__name__)

@login_required
def invitar_usuario(request, proyecto_id):
    """Vista para invitar usuarios al proyecto"""
    
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    
    # Verificar permisos
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto,
        puede_invitar=True
    ).first()
    
    es_admin = request.user.is_superuser or (
        hasattr(request.user, 'profile') and 
        request.user.profile.role and 
        request.user.profile.role.name == 'administrador'
    )
    
    if not usuario_proyecto and not es_admin:
        messages.error(request, 'No tienes permisos para invitar usuarios a este proyecto.')
        return redirect('detalle_proyecto', proyecto_id=proyecto_id)
    
    if request.method == 'POST':
        logger.debug(f"POST recibido: metodo={request.POST.get('metodo')}")
        metodo = request.POST.get('metodo')
        
        if metodo == 'usuario':
            usuario_id = request.POST.get('usuario_id', '').strip()
            
            if not usuario_id:
                messages.error(request, 'Debes seleccionar un usuario.')
                return render(request, 'invitar_usuario.html', {
                    'proyecto': proyecto,
                    'tab_activo': 'usuario'
                })
            
            try:
                usuario_invitado = get_object_or_404(User, id=usuario_id)
                
                if UsuarioProyecto.objects.filter(usuario=usuario_invitado, proyecto=proyecto).exists():
                    messages.error(request, 'Este usuario ya es miembro del proyecto.')
                else:
                    with transaction.atomic():
                        # Crear membresía
                        UsuarioProyecto.objects.create(
                            usuario=usuario_invitado,
                            proyecto=proyecto,
                            rol_proyecto='COLABORADOR',
                            puede_invitar=False
                        )
                        
                        # ✅ NOTIFICACIÓN AL USUARIO AGREGADO
                        crear_notificacion(
                            usuario=usuario_invitado,
                            tipo='invitacion_proyecto',
                            titulo=f'Te agregaron al proyecto: {proyecto.nombre}',
                            mensaje=f'{request.user.get_full_name() or request.user.username} te ha agregado al proyecto "{proyecto.nombre}" como colaborador.',
                            url=reverse('detalle_proyecto', args=[proyecto.id]),
                            proyecto=proyecto
                        )
                        
                        # Enviar email al usuario agregado
                        if usuario_invitado.email:
                            try:
                                send_mail(
                                    f'Te agregaron al proyecto: {proyecto.nombre}',
                                    f"""Hola {usuario_invitado.get_full_name() or usuario_invitado.username},

{request.user.get_full_name() or request.user.username} te ha agregado al proyecto "{proyecto.nombre}".

Ya puedes acceder al proyecto y comenzar a colaborar:
{request.build_absolute_uri(reverse('detalle_proyecto', args=[proyecto.id]))}

Saludos,
Equipo de Metaanálisis
""",
                                    settings.DEFAULT_FROM_EMAIL,
                                    [usuario_invitado.email],
                                    fail_silently=True,
                                )
                                logger.info(f"📧 Email enviado a {usuario_invitado.email}")
                            except Exception as e:
                                logger.error(f"❌ Error enviando email: {e}")
                        
                        logger.debug(f"✅ Usuario agregado: {usuario_invitado.username}")
                        messages.success(request, f'Usuario {usuario_invitado.get_full_name() or usuario_invitado.username} agregado exitosamente.')
                
                return redirect('detalle_proyecto', proyecto_id=proyecto_id)
                
            except User.DoesNotExist:
                logger.error("❌ Usuario no encontrado")
                messages.error(request, 'Usuario no encontrado.')
                return render(request, 'invitar_usuario.html', {
                    'proyecto': proyecto,
                    'tab_activo': 'usuario'
                })
        
        elif metodo == 'email':
            destinatario_email = request.POST.get('destinatario_email', '').strip()
            
            logger.debug(f"Invitación por email: destinatario={destinatario_email}")
            
            if not destinatario_email:
                messages.error(request, 'Debes proporcionar el correo del destinatario.')
                return render(request, 'invitar_usuario.html', {
                    'proyecto': proyecto,
                    'tab_activo': 'email'
                })
            
            # Validar dominios permitidos
            dominios_permitidos = ['@gmail.com', '@unemi.edu.ec']
            if not any(dominio in destinatario_email for dominio in dominios_permitidos):
                messages.error(request, 'Solo se permiten correos Gmail o @unemi.edu.ec')
                return render(request, 'invitar_usuario.html', {
                    'proyecto': proyecto,
                    'tab_activo': 'email'
                })
            
            try:
                invitacion_existente = Invitacion.objects.filter(
                    proyecto=proyecto,
                    email_destino=destinatario_email,
                    aceptado=False
                ).first()
                
                if invitacion_existente:
                    invitacion = invitacion_existente
                    logger.debug(f"Reutilizando invitación existente: {invitacion.token}")
                else:
                    token = get_random_string(length=32)
                    invitacion = Invitacion.objects.create(
                        proyecto=proyecto,
                        email_destino=destinatario_email,
                        token=token,
                        creado_por=request.user
                    )
                    logger.debug(f"✅ Invitación creada: token={token}")
                
                enlace_invitacion = request.build_absolute_uri(
                    reverse('aceptar_invitacion', args=[invitacion.token])
                )
                
                context = {
                    'proyecto': proyecto,
                    'invitacion': invitacion,
                    'enlace_invitacion': enlace_invitacion,
                    'destinatario_email': destinatario_email,
                    'remitente_nombre': request.user.get_full_name() or request.user.username,
                    'tab_activo': 'email'
                }
                
                messages.success(request, f'Invitación generada para {destinatario_email}.')
                return render(request, 'invitar_usuario.html', context)
                
            except Exception as e:
                logger.error(f"❌ Error al crear invitación: {str(e)}")
                messages.error(request, f'Error al registrar la invitación: {str(e)}')
                return render(request, 'invitar_usuario.html', {
                    'proyecto': proyecto,
                    'tab_activo': 'email'
                })
        
        else:
            logger.warning("⚠️ Método de invitación no válido")
            messages.error(request, 'Método de invitación no válido.')
            return render(request, 'invitar_usuario.html', {
                'proyecto': proyecto,
                'tab_activo': 'usuario'
            })
    
    # GET
    tab_activo = request.GET.get('tab', 'usuario')
    if tab_activo == 'nueva_invitacion':
        tab_activo = 'email'
    
    return render(request, 'invitar_usuario.html', {
        'proyecto': proyecto,
        'tab_activo': tab_activo
    })

from django.contrib.auth import get_user_model
from django.shortcuts import redirect, render
from django.contrib import messages
from django.urls import reverse
import datetime

User = get_user_model()

def aceptar_invitacion(request, token):
    """Vista para aceptar una invitación mediante token"""
    try:
        invitacion = Invitacion.objects.get(token=token, aceptado=False)
        
        # CASO 1: Usuario NO autenticado
        if not request.user.is_authenticated:
            # Verificar si existe una cuenta con ese email
            try:
                usuario_existente = User.objects.get(email__iexact=invitacion.email_destino)
                # Tiene cuenta pero no ha iniciado sesión
                request.session['invitacion_token'] = token
                messages.info(
                    request, 
                    f'Por favor, inicia sesión con tu cuenta ({invitacion.email_destino}) para aceptar la invitación.'
                )
                return redirect(f'/accounts/login/?next=/invitacion/aceptar/{token}/')
                
            except User.DoesNotExist:
                # NO tiene cuenta - debe registrarse
                request.session['invitacion_token'] = token
                request.session['invitacion_email'] = invitacion.email_destino
                messages.info(
                    request,
                    f'Esta invitación es para {invitacion.email_destino}. '
                    f'Por favor, crea una cuenta con ese email para continuar.'
                )
                return redirect(f'/usuarios/register/?email={invitacion.email_destino}&token={token}')
        
        # CASO 2: Usuario autenticado
        # Verificar que el email coincida
        if request.user.email.lower() != invitacion.email_destino.lower():
            messages.error(
                request, 
                f'Esta invitación fue enviada a {invitacion.email_destino}. '
                f'Tu cuenta está registrada con {request.user.email}. '
                f'Por favor, inicia sesión con la cuenta correcta.'
            )
            return redirect('core:home')
        
        # Verificar si ya es miembro
        if UsuarioProyecto.objects.filter(usuario=request.user, proyecto=invitacion.proyecto).exists():
            messages.warning(request, 'Ya eres miembro de este proyecto.')
            return redirect('detalle_proyecto', proyecto_id=invitacion.proyecto.id)
        
        # Agregar al usuario al proyecto
        UsuarioProyecto.objects.create(
            usuario=request.user,
            proyecto=invitacion.proyecto,
            rol_proyecto='COLABORADOR',
            puede_invitar=False
        )
        
        # Marcar la invitación como aceptada
        invitacion.aceptado = True
        invitacion.fecha_aceptacion = datetime.datetime.now()
        invitacion.save()
        
        # Crear notificaciones
        from .views import crear_notificacion
        
        crear_notificacion(
            usuario=request.user,
            tipo='invitacion_proyecto',
            titulo=f'Te uniste al proyecto: {invitacion.proyecto.nombre}',
            mensaje=f'Has sido agregado exitosamente al proyecto "{invitacion.proyecto.nombre}" como colaborador.',
            url=reverse('detalle_proyecto', args=[invitacion.proyecto.id]),
            proyecto=invitacion.proyecto
        )
        
        crear_notificacion(
            usuario=invitacion.creado_por,
            tipo='general',
            titulo=f'Invitación aceptada - {invitacion.proyecto.nombre}',
            mensaje=f'{request.user.get_full_name() or request.user.username} ha aceptado tu invitación y se unió al proyecto.',
            url=reverse('detalle_proyecto', args=[invitacion.proyecto.id]),
            proyecto=invitacion.proyecto
        )
        
        messages.success(request, f'¡Bienvenido al proyecto "{invitacion.proyecto.nombre}"!')
        logger.info(f"Usuario {request.user.username} aceptó invitación para proyecto {invitacion.proyecto.nombre}")
        
        return redirect('detalle_proyecto', proyecto_id=invitacion.proyecto.id)
        
    except Invitacion.DoesNotExist:
        messages.error(request, 'Esta invitación es inválida o ya ha sido utilizada.')
        logger.warning(f"Intento de acceso con token inválido: {token}")
        return redirect('core:home')

# ==================== SOLICITUDES Y MIEMBROS ====================

@login_required
@require_POST
def solicitar_unirse_proyecto(request, proyecto_id):
    """Vista para que un usuario solicite unirse a un proyecto"""
    
    try:
        proyecto = get_object_or_404(Proyecto, id=proyecto_id, estado='ACTIVO')
        
        # Verificar que el usuario no sea ya miembro
        ya_miembro = UsuarioProyecto.objects.filter(
            usuario=request.user,
            proyecto=proyecto
        ).exists()
        
        if ya_miembro:
            return JsonResponse({
                'success': False,
                'message': 'Ya eres miembro de este proyecto.'
            }, status=400)
        
        # Verificar si ya tiene una solicitud pendiente
        solicitud_existente = SolicitudProyecto.objects.filter(
            usuario=request.user,
            proyecto=proyecto,
            estado='PENDIENTE'
        ).exists()
        
        if solicitud_existente:
            return JsonResponse({
                'success': False,
                'message': 'Ya tienes una solicitud pendiente para este proyecto.'
            }, status=400)
        
        # Obtener el mensaje del request
        data = json.loads(request.body)
        mensaje = data.get('mensaje', '').strip()
        
        # Crear la solicitud
        with transaction.atomic():
            solicitud = SolicitudProyecto.objects.create(
                usuario=request.user,
                proyecto=proyecto,
                tipo_solicitud='UNIRSE',
                mensaje=mensaje,
                estado='PENDIENTE'
            )
            
            # 🔔 CREAR NOTIFICACIÓN IN-APP PARA EL DUEÑO
            try:
                dueno = UsuarioProyecto.objects.get(
                    proyecto=proyecto,
                    rol_proyecto='DUEÑO'
                ).usuario
                
                # Crear la notificación
                Notificacion.objects.create(
                    usuario=dueno,
                    tipo='nueva_solicitud',
                    titulo=f'Nueva solicitud para {proyecto.nombre}',
                    mensaje=f'{request.user.get_full_name() or request.user.username} ha solicitado unirse a tu proyecto.',
                    url=reverse('detalle_proyecto', args=[proyecto.id]),
                    proyecto=proyecto,
                    solicitud=solicitud
                )
                
                # Enviar email
                if dueno.email:
                    asunto = f'Nueva solicitud para "{proyecto.nombre}"'
                    mensaje_email = f"""Hola {dueno.get_full_name() or dueno.username},

{request.user.get_full_name() or request.user.username} ha solicitado unirse a tu proyecto "{proyecto.nombre}".

{f'Mensaje: "{mensaje}"' if mensaje else 'No incluyó un mensaje.'}

Puedes revisar y gestionar esta solicitud en:
{request.build_absolute_uri(reverse('detalle_proyecto', args=[proyecto.id]))}

Saludos,
Equipo de Metaanálisis
"""
                    
                    send_mail(
                        asunto,
                        mensaje_email,
                        settings.DEFAULT_FROM_EMAIL,
                        [dueno.email],
                        fail_silently=True,
                    )
            except UsuarioProyecto.DoesNotExist:
                pass
            except Exception as e:
                # Si falla la notificación, continuar de todos modos
                print(f"Error creando notificación: {e}")
        
        return JsonResponse({
            'success': True,
            'message': 'Solicitud enviada exitosamente. El administrador del proyecto revisará tu solicitud.'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error al enviar la solicitud: {str(e)}'
        }, status=500)

@login_required
@require_POST
def gestionar_solicitud(request, solicitud_id):
    """Vista para aceptar o rechazar solicitudes"""
    
    try:
        solicitud = get_object_or_404(SolicitudProyecto, id=solicitud_id, estado='PENDIENTE')
        
        # Verificar permisos (debe ser dueño o supervisor)
        usuario_proyecto = UsuarioProyecto.objects.filter(
            usuario=request.user,
            proyecto=solicitud.proyecto,
            rol_proyecto__in=['DUEÑO', 'SUPERVISOR']
        ).first()
        
        if not usuario_proyecto and not request.user.is_superuser:
            return JsonResponse({
                'success': False,
                'message': 'No tienes permisos para gestionar solicitudes.'
            }, status=403)
        
        data = json.loads(request.body)
        accion = data.get('accion')  # 'aceptar' o 'rechazar'
        
        if accion not in ['aceptar', 'rechazar']:
            return JsonResponse({
                'success': False,
                'message': 'Acción no válida.'
            }, status=400)
        
        with transaction.atomic():
            if accion == 'aceptar':
                # Verificar nuevamente que no sea miembro
                if UsuarioProyecto.objects.filter(
                    usuario=solicitud.usuario,
                    proyecto=solicitud.proyecto
                ).exists():
                    return JsonResponse({
                        'success': False,
                        'message': 'El usuario ya es miembro del proyecto.'
                    }, status=400)
                
                # Crear el usuario en el proyecto
                UsuarioProyecto.objects.create(
                    usuario=solicitud.usuario,
                    proyecto=solicitud.proyecto,
                    rol_proyecto='COLABORADOR',
                    puede_invitar=False
                )
                
                solicitud.estado = 'APROBADA'
                solicitud.respondido_por = request.user
                solicitud.fecha_respuesta = timezone.now()
                solicitud.save()
                
                mensaje_respuesta = f'{solicitud.usuario.get_full_name() or solicitud.usuario.username} ha sido agregado al proyecto.'
                
                # CREAR NOTIFICACIÓN IN-APP
                crear_notificacion(
                    usuario=solicitud.usuario,
                    tipo='solicitud_aceptada',
                    titulo=f'¡Solicitud aceptada! - {solicitud.proyecto.nombre}',
                    mensaje=f'Tu solicitud para unirte al proyecto "{solicitud.proyecto.nombre}" ha sido aceptada.',
                    url=reverse('detalle_proyecto', args=[solicitud.proyecto.id]),
                    proyecto=solicitud.proyecto,
                    solicitud=solicitud
                )
                
                # Enviar email
                if solicitud.usuario.email:
                    try:
                        send_mail(
                            f'¡Solicitud aceptada! - {solicitud.proyecto.nombre}',
                            f"""Hola {solicitud.usuario.get_full_name() or solicitud.usuario.username},

¡Buenas noticias! Tu solicitud para unirte al proyecto "{solicitud.proyecto.nombre}" ha sido aceptada.

Ya puedes acceder al proyecto y comenzar a colaborar:
{request.build_absolute_uri(reverse('detalle_proyecto', args=[solicitud.proyecto.id]))}

Saludos,
Equipo de Metaanálisis
""",
                            settings.DEFAULT_FROM_EMAIL,
                            [solicitud.usuario.email],
                            fail_silently=True,
                        )
                    except Exception as e:
                        print(f"Error enviando email: {e}")
                
            else:  # rechazar
                solicitud.estado = 'RECHAZADA'
                solicitud.respondido_por = request.user
                solicitud.fecha_respuesta = timezone.now()
                solicitud.save()
                
                mensaje_respuesta = 'Solicitud rechazada.'
                
                # CREAR NOTIFICACIÓN IN-APP
                crear_notificacion(
                    usuario=solicitud.usuario,
                    tipo='solicitud_rechazada',
                    titulo=f'Solicitud rechazada - {solicitud.proyecto.nombre}',
                    mensaje=f'Tu solicitud para unirte al proyecto "{solicitud.proyecto.nombre}" no ha sido aceptada en este momento.',
                    url=reverse('buscar_proyectos'),
                    proyecto=solicitud.proyecto,
                    solicitud=solicitud
                )
                
                # Enviar email
                if solicitud.usuario.email:
                    try:
                        send_mail(
                            f'Actualización de solicitud - {solicitud.proyecto.nombre}',
                            f"""Hola {solicitud.usuario.get_full_name() or solicitud.usuario.username},

Tu solicitud para unirte al proyecto "{solicitud.proyecto.nombre}" no ha sido aceptada en este momento.

Puedes buscar otros proyectos que puedan interesarte en la plataforma.

Saludos,
Equipo de Metaanálisis
""",
                            settings.DEFAULT_FROM_EMAIL,
                            [solicitud.usuario.email],
                            fail_silently=True,
                        )
                    except Exception as e:
                        print(f"Error enviando email: {e}")
        
        return JsonResponse({
            'success': True,
            'message': mensaje_respuesta
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error al gestionar la solicitud: {str(e)}'
        }, status=500)

@login_required
def buscar_usuarios_disponibles(request, proyecto_id):
    """Vista AJAX para buscar usuarios disponibles para invitar"""
    
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Petición no válida'}, status=400)
    
    try:
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
        
        # Verificar permisos
        usuario_proyecto = UsuarioProyecto.objects.filter(
            usuario=request.user,
            proyecto=proyecto,
            puede_invitar=True
        ).first()
        
        es_admin = request.user.is_superuser or (
            hasattr(request.user, 'profile') and 
            request.user.profile.role and 
            request.user.profile.role.name == 'administrador'
        )
        
        if not usuario_proyecto and not es_admin:
            return JsonResponse({'error': 'Sin permisos'}, status=403)
        
        # Obtener término de búsqueda
        query = request.GET.get('q', '').strip()
        
        if len(query) < 2:
            return JsonResponse({
                'success': True,
                'usuarios': []
            })
        
        # Obtener IDs de usuarios que ya son miembros
        miembros_ids = UsuarioProyecto.objects.filter(
            proyecto=proyecto
        ).values_list('usuario_id', flat=True)
        
        # Buscar usuarios que NO sean miembros
        usuarios = User.objects.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query)
        ).exclude(
            id__in=miembros_ids
        ).exclude(
            id=request.user.id  # Excluir al usuario actual
        )[:10]  # Limitar a 10 resultados
        
        usuarios_data = []
        for usuario in usuarios:
            usuarios_data.append({
                'id': usuario.id,
                'username': usuario.username,
                'nombre_completo': usuario.get_full_name() or usuario.username,
                'email': usuario.email,
                'iniciales': (usuario.first_name[0] if usuario.first_name else usuario.username[0]).upper()
            })
        
        return JsonResponse({
            'success': True,
            'usuarios': usuarios_data
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@require_POST
def cambiar_rol_miembro(request, proyecto_id, usuario_id):
    """Vista para cambiar el rol de un miembro del proyecto"""
    
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Petición no válida'}, status=400)
    
    try:
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
        
        # Verificar permisos (solo dueño puede cambiar roles)
        usuario_proyecto_gestor = UsuarioProyecto.objects.filter(
            usuario=request.user,
            proyecto=proyecto,
            rol_proyecto='DUEÑO'
        ).first()
        
        if not usuario_proyecto_gestor and not request.user.is_superuser:
            return JsonResponse({
                'success': False,
                'message': 'No tienes permisos para cambiar roles.'
            }, status=403)
        
        # Obtener el miembro a modificar
        miembro = get_object_or_404(
            UsuarioProyecto,
            proyecto=proyecto,
            usuario_id=usuario_id
        )
        
        # No permitir cambiar el rol del dueño
        if miembro.rol_proyecto == 'DUEÑO':
            return JsonResponse({
                'success': False,
                'message': 'No se puede cambiar el rol del dueño del proyecto.'
            }, status=400)
        
        # Obtener el nuevo rol
        data = json.loads(request.body)
        nuevo_rol = data.get('rol')
        
        if nuevo_rol not in ['SUPERVISOR', 'COLABORADOR']:
            return JsonResponse({
                'success': False,
                'message': 'Rol no válido.'
            }, status=400)
        
        # Actualizar el rol
        rol_anterior = miembro.get_rol_proyecto_display()
        miembro.rol_proyecto = nuevo_rol
        miembro.puede_invitar = (nuevo_rol in ['SUPERVISOR'])
        miembro.save()
        
        # Crear notificación
        crear_notificacion(
            usuario=miembro.usuario,
            tipo='cambio_rol',
            titulo=f'Cambio de rol - {proyecto.nombre}',
            mensaje=f'Tu rol en el proyecto "{proyecto.nombre}" ha cambiado de {rol_anterior} a {miembro.get_rol_proyecto_display()}.',
            url=reverse('detalle_proyecto', args=[proyecto.id]),
            proyecto=proyecto
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Rol cambiado a {miembro.get_rol_proyecto_display()}',
            'nuevo_rol': miembro.get_rol_proyecto_display(),
            'puede_invitar': miembro.puede_invitar
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error al cambiar el rol: {str(e)}'
        }, status=500)

@login_required
@require_POST
def eliminar_miembro(request, proyecto_id, usuario_id):
    """Vista para eliminar un miembro del proyecto"""
    
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Petición no válida'}, status=400)
    
    try:
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
        
        # Verificar permisos (dueño o supervisor pueden eliminar)
        usuario_proyecto_gestor = UsuarioProyecto.objects.filter(
            usuario=request.user,
            proyecto=proyecto,
            rol_proyecto__in=['DUEÑO', 'SUPERVISOR']
        ).first()
        
        if not usuario_proyecto_gestor and not request.user.is_superuser:
            return JsonResponse({
                'success': False,
                'message': 'No tienes permisos para eliminar miembros.'
            }, status=403)
        
        # Obtener el miembro a eliminar
        miembro = get_object_or_404(
            UsuarioProyecto,
            proyecto=proyecto,
            usuario_id=usuario_id
        )
        
        # No permitir eliminar al dueño
        if miembro.rol_proyecto == 'DUEÑO':
            return JsonResponse({
                'success': False,
                'message': 'No se puede eliminar al dueño del proyecto.'
            }, status=400)
        
        # No permitirse eliminar a sí mismo
        if miembro.usuario == request.user:
            return JsonResponse({
                'success': False,
                'message': 'No puedes eliminarte a ti mismo. Usa la opción "Abandonar proyecto".'
            }, status=400)
        
        # Guardar datos antes de eliminar
        nombre_usuario = miembro.usuario.get_full_name() or miembro.usuario.username
        usuario_eliminado = miembro.usuario
        
        # Eliminar el miembro
        miembro.delete()
        
        # Crear notificación
        crear_notificacion(
            usuario=usuario_eliminado,
            tipo='general',
            titulo=f'Removido del proyecto - {proyecto.nombre}',
            mensaje=f'Has sido removido del proyecto "{proyecto.nombre}".',
            url=reverse('buscar_proyectos'),
            proyecto=None
        )
        
        return JsonResponse({
            'success': True,
            'message': f'{nombre_usuario} ha sido eliminado del proyecto.'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error al eliminar el miembro: {str(e)}'
        }, status=500)

@login_required
@require_POST
def abandonar_proyecto(request, proyecto_id):
    """Vista para que un usuario abandone voluntariamente un proyecto"""
    
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Petición no válida'}, status=400)
    
    try:
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
        
        # Obtener la membresía del usuario
        miembro = UsuarioProyecto.objects.filter(
            usuario=request.user,
            proyecto=proyecto
        ).first()
        
        if not miembro:
            return JsonResponse({
                'success': False,
                'message': 'No eres miembro de este proyecto.'
            }, status=400)
        
        # El dueño no puede abandonar su propio proyecto
        if miembro.rol_proyecto == 'DUEÑO':
            return JsonResponse({
                'success': False,
                'message': 'No puedes abandonar un proyecto del que eres dueño. Debes transferir la propiedad primero o eliminar el proyecto.'
            }, status=400)
        
        # Guardar datos antes de eliminar
        nombre_proyecto = proyecto.nombre
        nombre_usuario = request.user.get_full_name() or request.user.username
        
        with transaction.atomic():
            # Eliminar la membresía
            miembro.delete()
            
            # Notificar al dueño del proyecto (IN-APP)
            try:
                dueno = UsuarioProyecto.objects.get(
                    proyecto=proyecto,
                    rol_proyecto='DUEÑO'
                ).usuario
                
                # Crear notificación in-app
                crear_notificacion(
                    usuario=dueno,
                    tipo='general',
                    titulo=f'Miembro abandonó proyecto - {nombre_proyecto}',
                    mensaje=f'{nombre_usuario} ha abandonado el proyecto "{nombre_proyecto}".',
                    url=reverse('detalle_proyecto', args=[proyecto.id]),
                    proyecto=proyecto
                )
                
                # Enviar email al dueño
                if dueno.email:
                    try:
                        send_mail(
                            f'Miembro abandonó proyecto - {nombre_proyecto}',
                            f"""Hola {dueno.get_full_name() or dueno.username},

Te informamos que {nombre_usuario} ha abandonado el proyecto "{nombre_proyecto}".

Puedes revisar el estado del proyecto aquí:
{request.build_absolute_uri(reverse('detalle_proyecto', args=[proyecto.id]))}

Saludos,
Equipo de Metaanálisis
""",
                            settings.DEFAULT_FROM_EMAIL,
                            [dueno.email],
                            fail_silently=True,
                        )
                    except Exception as e:
                        print(f"Error enviando email: {e}")
                        
            except UsuarioProyecto.DoesNotExist:
                pass
        
        return JsonResponse({
            'success': True,
            'message': f'Has abandonado el proyecto "{nombre_proyecto}".',
            'redirect': reverse('mis_proyectos')
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error al abandonar el proyecto: {str(e)}'
        }, status=500)

# ==================== SISTEMA DE NOTIFICACIONES ====================

@login_required
def obtener_notificaciones(request):
    """Vista para obtener las notificaciones del usuario (AJAX)"""
    
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Petición no válida'}, status=400)
    
    try:
        # Obtener las últimas 10 notificaciones
        notificaciones = Notificacion.objects.filter(
            usuario=request.user
        ).select_related('proyecto', 'solicitud')[:10]
        
        from django.utils.timesince import timesince
        
        notificaciones_data = []
        for notif in notificaciones:
            notificaciones_data.append({
                'id': notif.id,
                'tipo': notif.tipo,
                'titulo': notif.titulo,
                'mensaje': notif.mensaje,
                'leida': notif.leida,
                'url': notif.url or '#',
                'tiempo_relativo': f'hace {timesince(notif.fecha_creacion)}',
                'fecha_creacion': notif.fecha_creacion.isoformat(),
            })
        
        # Contar no leídas
        no_leidas = Notificacion.objects.filter(
            usuario=request.user,
            leida=False
        ).count()
        
        return JsonResponse({
            'success': True,
            'notificaciones': notificaciones_data,
            'no_leidas': no_leidas
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def contar_notificaciones(request):
    """Vista para contar notificaciones no leídas (AJAX - polling)"""
    
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Petición no válida'}, status=400)
    
    try:
        no_leidas = Notificacion.objects.filter(
            usuario=request.user,
            leida=False
        ).count()
        
        return JsonResponse({
            'success': True,
            'no_leidas': no_leidas
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@require_POST
def marcar_notificacion_leida(request, notificacion_id):
    """Vista para marcar una notificación como leída (AJAX)"""
    
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Petición no válida'}, status=400)
    
    try:
        notificacion = get_object_or_404(
            Notificacion,
            id=notificacion_id,
            usuario=request.user
        )
        
        notificacion.marcar_como_leida()
        
        return JsonResponse({
            'success': True,
            'message': 'Notificación marcada como leída',
            'url': notificacion.url
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@require_POST
def marcar_todas_notificaciones_leidas(request):
    """Vista para marcar todas las notificaciones como leídas (AJAX)"""
    
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Petición no válida'}, status=400)
    
    try:
        actualizadas = Notificacion.objects.filter(
            usuario=request.user,
            leida=False
        ).update(
            leida=True,
            fecha_lectura=timezone.now()
        )
        
        return JsonResponse({
            'success': True,
            'message': f'{actualizadas} notificaciones marcadas como leídas'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

