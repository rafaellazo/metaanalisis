from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, Q, Avg, Sum, F
from django.utils import timezone
from datetime import timedelta
from usuarios.models import Role

# Importar modelos de proyectos y artículos
try:
    from pymetanalis.models import Proyecto, UsuarioProyecto, SolicitudProyecto, Notificacion
    from articulos.models import Articulo, AsignacionCampo, HistorialArticulo, ComentarioRevision
    PROYECTOS_APP_INSTALLED = True
except ImportError:
    PROYECTOS_APP_INSTALLED = False


def home_view(request):
    """Vista principal del dashboard con datos según el rol del usuario"""
    
    context = {
        'total_usuarios': 0,
        'total_roles': 0,
        'total_articulos': 0,
        'total_analisis': 0,
        'revisiones_pendientes': 0,
    }
    
    # Si el usuario está autenticado
    if request.user.is_authenticated:
        # Verificar si es superusuario o administrador
        is_admin = request.user.is_superuser
        
        if hasattr(request.user, 'profile') and request.user.profile.role:
            is_admin = is_admin or request.user.profile.role.name == 'administrador'
        
        # ==================== DASHBOARD PARA ADMINISTRADOR ====================
        if is_admin and PROYECTOS_APP_INSTALLED:
            # ===== ESTADÍSTICAS GENERALES =====
            context['total_usuarios'] = User.objects.filter(is_active=True).count()
            context['total_roles'] = Role.objects.count()
            context['total_proyectos'] = Proyecto.objects.count()
            context['total_articulos'] = Articulo.objects.count()
            
            # Proyectos activos
            proyectos_activos = Proyecto.objects.filter(estado='ACTIVO').count()
            context['proyectos_activos'] = proyectos_activos
            
            # Artículos en revisión (necesitan atención)
            context['revisiones_pendientes'] = Articulo.objects.filter(
                estado='EN_REVISION'
            ).count()
            
            # Solicitudes pendientes de proyectos
            context['solicitudes_pendientes'] = SolicitudProyecto.objects.filter(
                estado='PENDIENTE'
            ).count()
            
            # ===== ESTADÍSTICAS DE ARTÍCULOS POR ESTADO =====
            articulos_por_estado = Articulo.objects.values('estado').annotate(
                total=Count('id')
            ).order_by('-total')
            
            # Definir colores para estados de artículos
            COLORES_ESTADO_ARTICULOS = {
                'EN_ESPERA': '#6b7280',      # gray-500
                'PENDIENTE': '#f59e0b',      # amber-500
                'EN_PROCESO': '#3b82f6',     # blue-500
                'EN_REVISION': '#8b5cf6',    # violet-500
                'APROBADO': '#10b981'        # green-500
            }
            
            total_articulos_sistema = sum([a['total'] for a in articulos_por_estado])
            articulos_estado_data = []
            
            # Calcular offset acumulativo para el gráfico de dona
            offset_acumulado = 0
            
            for estado in articulos_por_estado:
                estado_nombre = dict(Articulo.ESTADO_CHOICES).get(estado['estado'], estado['estado'])
                porcentaje = (estado['total'] / total_articulos_sistema * 100) if total_articulos_sistema > 0 else 0
                
                articulos_estado_data.append({
                    'nombre': estado_nombre,
                    'total': estado['total'],
                    'porcentaje': round(porcentaje, 1),
                    'color': COLORES_ESTADO_ARTICULOS.get(estado['estado'], '#6b7280'),
                    'offset': offset_acumulado  # Agregar offset para SVG
                })
                
                # Actualizar offset para el siguiente segmento
                offset_acumulado += porcentaje
            
            context['articulos_por_estado'] = articulos_estado_data
            context['total_articulos_sistema'] = total_articulos_sistema
            
            # ===== PROYECTOS POR CATEGORÍA (GLOBAL) =====
            proyectos_por_cat = Proyecto.objects.values('categoria').annotate(
                total=Count('id')
            ).order_by('-total')[:5]
            
            COLORES_CATEGORIA = {
                'SALUD': '#10b981',            # green-500
                'TECNOLOGIA': '#3b82f6',       # blue-500
                'EDUCACION': '#f59e0b',        # amber-500
                'PSICOLOGIA': '#8b5cf6',       # violet-500
                'ECONOMIA': '#ef4444',         # red-500
                'CIENCIAS_SOCIALES': '#ec4899', # pink-500
                'INGENIERIA': '#6366f1',       # indigo-500
                'OTRO': '#6b7280'              # gray-500
            }
            
            total_proyectos_cat_admin = sum([p['total'] for p in proyectos_por_cat])
            categorias_data = []
            
            for cat in proyectos_por_cat:
                cat_nombre = dict(Proyecto.CATEGORIA_CHOICES).get(cat['categoria'], cat['categoria'])
                porcentaje = (cat['total'] / total_proyectos_cat_admin * 100) if total_proyectos_cat_admin > 0 else 0
                
                categorias_data.append({
                    'nombre': cat_nombre,
                    'total': cat['total'],
                    'porcentaje': round(porcentaje, 1),
                    'color': COLORES_CATEGORIA.get(cat['categoria'], '#6b7280')
                })
            
            context['proyectos_por_categoria'] = categorias_data
            
            # ===== ACTIVIDAD RECIENTE (Últimos 10 cambios) =====
            actividad_reciente = HistorialArticulo.objects.select_related(
                'articulo', 'usuario', 'articulo__proyecto'
            ).order_by('-fecha_cambio')[:10]
            
            context['actividad_reciente'] = actividad_reciente
            
            # ===== USUARIOS MÁS ACTIVOS (Por artículos trabajados) =====
            usuarios_activos = User.objects.filter(
                Q(articulos_asignados__isnull=False) | Q(articulos_subidos__isnull=False)
            ).annotate(
                total_articulos=Count('articulos_asignados', distinct=True) + Count('articulos_subidos', distinct=True)
            ).order_by('-total_articulos')[:5]
            
            context['usuarios_activos'] = usuarios_activos
            
            # ===== PROYECTOS RECIENTES =====
            proyectos_recientes = Proyecto.objects.select_related(
                'creado_por'
            ).order_by('-fecha_creacion')[:5]
            
            context['proyectos_recientes'] = proyectos_recientes
            
            # ===== ESTADÍSTICAS DE PROGRESO GENERAL =====
            proyectos_con_datos = Proyecto.objects.exclude(
                total_articulos=0
            ).annotate(
                progreso_calc=F('articulos_trabajados') * 100.0 / F('total_articulos')
            )
            
            progreso_promedio = proyectos_con_datos.aggregate(
                Avg('progreso_calc')
            )['progreso_calc__avg'] or 0
            
            context['progreso_promedio_sistema'] = round(progreso_promedio, 1)
            
            # ===== NOTIFICACIONES NO LEÍDAS (SISTEMA) =====
            context['notificaciones_sistema'] = Notificacion.objects.filter(
                leida=False
            ).count()
        
        # ==================== DASHBOARD PARA INVESTIGADOR ====================
        elif hasattr(request.user, 'profile') and request.user.profile.role and \
             request.user.profile.role.name == 'investigador' and PROYECTOS_APP_INSTALLED:
            
            # ===== OBTENER PROYECTOS DEL USUARIO =====
            usuario_proyectos = UsuarioProyecto.objects.filter(
                usuario=request.user
            ).select_related('proyecto')
            
            # ===== ESTADÍSTICAS GENERALES =====
            total_proyectos = usuario_proyectos.count()
            proyectos_dueno = usuario_proyectos.filter(rol_proyecto='DUEÑO').count()
            proyectos_supervisor = usuario_proyectos.filter(rol_proyecto='SUPERVISOR').count()
            proyectos_colaborador = usuario_proyectos.filter(rol_proyecto='COLABORADOR').count()
            
            context.update({
                'total_proyectos': total_proyectos,
                'proyectos_dueno': proyectos_dueno,
                'proyectos_supervisor': proyectos_supervisor,
                'proyectos_colaborador': proyectos_colaborador,
            })
            
            # ===== MIS ARTÍCULOS - ESTADÍSTICAS =====
            mis_articulos = Articulo.objects.filter(
                Q(usuario_asignado=request.user) | Q(usuario_carga=request.user)
            ).distinct()
            
            total_mis_articulos = mis_articulos.count()
            mis_articulos_pendientes = mis_articulos.filter(
                estado__in=['PENDIENTE', 'EN_PROCESO']
            ).count()
            mis_articulos_revision = mis_articulos.filter(estado='EN_REVISION').count()
            mis_articulos_aprobados = mis_articulos.filter(estado='APROBADO').count()
            
            # Calcular progreso personal
            progreso_personal = 0
            if total_mis_articulos > 0:
                progreso_personal = round((mis_articulos_aprobados / total_mis_articulos) * 100, 1)
            
            context.update({
                'total_mis_articulos': total_mis_articulos,
                'mis_articulos_pendientes': mis_articulos_pendientes,
                'mis_articulos_revision': mis_articulos_revision,
                'mis_articulos_aprobados': mis_articulos_aprobados,
                'progreso_personal': progreso_personal,
            })
            
            # ===== TAREAS PENDIENTES (Campos sin completar) =====
            campos_pendientes = AsignacionCampo.objects.filter(
                articulo__usuario_asignado=request.user,
                completado=False,
                articulo__estado__in=['PENDIENTE', 'EN_PROCESO']
            ).count()
            
            context['tareas_pendientes'] = campos_pendientes
            
            # ===== SOLICITUDES PENDIENTES (Si es dueño o supervisor) =====
            proyectos_gestion = usuario_proyectos.filter(
                rol_proyecto__in=['DUEÑO', 'SUPERVISOR']
            ).values_list('proyecto_id', flat=True)
            
            solicitudes_pendientes = SolicitudProyecto.objects.filter(
                proyecto_id__in=proyectos_gestion,
                estado='PENDIENTE'
            ).count()
            
            context['solicitudes_pendientes'] = solicitudes_pendientes
            
            # ===== ARTÍCULOS PARA REVISAR (Si es supervisor o dueño) =====
            if proyectos_gestion:
                articulos_por_revisar = Articulo.objects.filter(
                    proyecto_id__in=proyectos_gestion,
                    estado='EN_REVISION'
                ).count()
                context['articulos_por_revisar'] = articulos_por_revisar
            else:
                context['articulos_por_revisar'] = 0
            
            # ===== NOTIFICACIONES NO LEÍDAS =====
            notificaciones_pendientes = Notificacion.objects.filter(
                usuario=request.user,
                leida=False
            ).count()
            context['notificaciones_pendientes'] = notificaciones_pendientes
            
            # ===== PROYECTOS RECIENTES (últimos 5 con detalles) =====
            proyectos_recientes_data = []
            
            # Definir colores para roles
            COLORES_ROL = {
                'DUEÑO': 'purple',
                'SUPERVISOR': 'blue',
                'COLABORADOR': 'green'
            }
            
            for up in usuario_proyectos.select_related('proyecto').order_by('-fecha_incorporacion')[:5]:
                proyecto = up.proyecto
                
                # Calcular progreso real
                progreso = 0
                if proyecto.total_articulos > 0:
                    articulos_aprobados = Articulo.objects.filter(
                        proyecto=proyecto,
                        estado='APROBADO'
                    ).count()
                    progreso = round((articulos_aprobados / proyecto.total_articulos) * 100, 1)
                
                # Mis artículos en este proyecto
                mis_articulos_proyecto = Articulo.objects.filter(
                    Q(usuario_asignado=request.user) | Q(usuario_carga=request.user),
                    proyecto=proyecto
                ).distinct().count()
                
                proyectos_recientes_data.append({
                    'proyecto': proyecto,
                    'rol': up.get_rol_proyecto_display(),
                    'progreso': progreso,
                    'mis_articulos': mis_articulos_proyecto,
                    'color_rol': COLORES_ROL.get(up.rol_proyecto, 'gray')
                })
            
            context['proyectos_recientes'] = proyectos_recientes_data
            
            # ===== ACTIVIDAD RECIENTE (Mis cambios en artículos) =====
            mi_actividad = HistorialArticulo.objects.filter(
                usuario=request.user
            ).select_related(
                'articulo', 'articulo__proyecto'
            ).order_by('-fecha_cambio')[:8]
            
            context['mi_actividad'] = mi_actividad
            
            # ===== COMENTARIOS RECIENTES (Recibidos o enviados) =====
            comentarios_recientes = ComentarioRevision.objects.filter(
                Q(colaborador=request.user) | Q(supervisor=request.user)
            ).select_related(
                'articulo', 'supervisor', 'colaborador', 'articulo__proyecto'
            ).order_by('-fecha_comentario')[:5]
            
            context['comentarios_recientes'] = comentarios_recientes
            
            # ===== PROYECTOS POR CATEGORÍA (Mis proyectos) =====
            proyectos_ids = usuario_proyectos.values_list('proyecto_id', flat=True)
            proyectos_por_cat = Proyecto.objects.filter(
                id__in=proyectos_ids
            ).values('categoria').annotate(total=Count('id')).order_by('-total')
            
            COLORES_CATEGORIA = {
                'SALUD': '#10b981',
                'TECNOLOGIA': '#3b82f6',
                'EDUCACION': '#f59e0b',
                'PSICOLOGIA': '#8b5cf6',
                'ECONOMIA': '#ef4444',
                'CIENCIAS_SOCIALES': '#ec4899',
                'INGENIERIA': '#6366f1',
                'OTRO': '#6b7280'
            }
            
            proyectos_por_categoria = []
            total_proyectos_cat = sum([p['total'] for p in proyectos_por_cat])
            
            for cat in proyectos_por_cat:
                categoria_display = dict(Proyecto.CATEGORIA_CHOICES).get(cat['categoria'], cat['categoria'])
                porcentaje = (cat['total'] / total_proyectos_cat * 100) if total_proyectos_cat > 0 else 0
                
                proyectos_por_categoria.append({
                    'nombre': categoria_display,
                    'total': cat['total'],
                    'porcentaje': round(porcentaje, 1),
                    'color': COLORES_CATEGORIA.get(cat['categoria'], '#6b7280')
                })
            
            context['proyectos_por_categoria'] = proyectos_por_categoria
            
            # ===== PROYECTOS POR ESTADO =====
            proyectos_por_est = Proyecto.objects.filter(
                id__in=proyectos_ids
            ).values('estado').annotate(total=Count('id')).order_by('-total')
            
            COLORES_ESTADO = {
                'ACTIVO': '#10b981',
                'PAUSADO': '#f59e0b',
                'FINALIZADO': '#6b7280',
                'ARCHIVADO': '#ef4444'
            }
            
            proyectos_por_estado = []
            total_proyectos_est = sum([e['total'] for e in proyectos_por_est])
            
            for est in proyectos_por_est:
                estado_display = dict(Proyecto.ESTADO_CHOICES).get(est['estado'], est['estado'])
                porcentaje = (est['total'] / total_proyectos_est * 100) if total_proyectos_est > 0 else 0
                
                proyectos_por_estado.append({
                    'nombre': estado_display,
                    'total': est['total'],
                    'porcentaje': round(porcentaje, 1),
                    'color': COLORES_ESTADO.get(est['estado'], '#6b7280')
                })
            
            context['proyectos_por_estado'] = proyectos_por_estado
            
            # ===== ESTADÍSTICAS DE MIS ARTÍCULOS POR ESTADO =====
            mis_articulos_por_estado = mis_articulos.values('estado').annotate(
                total=Count('id')
            ).order_by('-total')
            
            COLORES_ESTADO_ARTICULOS = {
                'EN_ESPERA': '#6b7280',
                'PENDIENTE': '#f59e0b',
                'EN_PROCESO': '#3b82f6',
                'EN_REVISION': '#8b5cf6',
                'APROBADO': '#10b981'
            }
            
            mis_articulos_estado_data = []
            for estado in mis_articulos_por_estado:
                estado_nombre = dict(Articulo.ESTADO_CHOICES).get(estado['estado'], estado['estado'])
                porcentaje = (estado['total'] / total_mis_articulos * 100) if total_mis_articulos > 0 else 0
                
                mis_articulos_estado_data.append({
                    'nombre': estado_nombre,
                    'total': estado['total'],
                    'porcentaje': round(porcentaje, 1),
                    'color': COLORES_ESTADO_ARTICULOS.get(estado['estado'], '#6b7280')
                })
            
            context['mis_articulos_por_estado'] = mis_articulos_estado_data
            
            # ===== PRODUCTIVIDAD SEMANAL =====
            hace_7_dias = timezone.now() - timedelta(days=7)
            
            articulos_completados_semana = HistorialArticulo.objects.filter(
                usuario=request.user,
                tipo_cambio='CAMBIO_ESTADO',
                valor_nuevo='APROBADO',
                fecha_cambio__gte=hace_7_dias
            ).count()
            
            campos_completados_semana = AsignacionCampo.objects.filter(
                articulo__usuario_asignado=request.user,
                completado=True,
                fecha_completado__gte=hace_7_dias
            ).count()
            
            context.update({
                'articulos_completados_semana': articulos_completados_semana,
                'campos_completados_semana': campos_completados_semana,
            })
    
    return render(request, 'home.html', context)