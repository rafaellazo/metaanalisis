# ==================== CAMBIOS NECESARIOS EN LOS MODELOS ====================

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from pymetanalis.models import Proyecto
import os


# Función para organizar archivos PDF por proyecto/usuario
def upload_pdf_to(instance, filename):
    """Genera ruta organizada para PDFs: proyectos/{proyecto}/articulos/{usuario}/PDFs/{filename}"""
    # Limpiar nombre de proyecto y usuario para evitar caracteres problemáticos
    proyecto_limpio = "".join(c for c in instance.proyecto.nombre if c.isalnum() or c in (' ', '-', '_')).rstrip()
    usuario = instance.usuario_asignado or instance.proyecto.usuario_creador
    usuario_limpio = "".join(c for c in usuario.username if c.isalnum() or c in (' ', '-', '_')).rstrip()
    
    # Crear ruta
    return f"proyectos/{proyecto_limpio}/articulos/{usuario_limpio}/PDFs/{filename}"


# ==================== 1. MODELO ARTICULO - SIN CAMBIOS MAYORES ====================
# ✅ ESTÁ BIEN, solo pequeños ajustes en la documentación

class Articulo(models.Model):
    """Modelo principal de artículos con sistema de estados mejorado"""
    
    ESTADO_CHOICES = [
        ('EN_ESPERA', 'En Espera'),       # ⚠️ YA NO SE USARÁ (todos inician en PENDIENTE)
        ('PENDIENTE', 'Pendiente'),       # ✅ Estado inicial (con tareas asignadas)
        ('EN_PROCESO', 'En Proceso'),
        ('EN_REVISION', 'En Revisión'),
        ('APROBADO', 'Aprobado'),
    ]
    
    # Relaciones base
    proyecto = models.ForeignKey(
        Proyecto, 
        on_delete=models.CASCADE, 
        related_name='articulos'
    )
    usuario_carga = models.ForeignKey(
        User, 
        on_delete=models.PROTECT, 
        related_name='articulos_subidos',
        help_text='Usuario que subió el artículo'
    )
    usuario_asignado = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='articulos_asignados',
        help_text='Colaborador asignado para trabajar en este artículo'
    )
    
    # Datos bibliográficos
    bibtex_key = models.CharField(max_length=200, unique=True)
    titulo = models.CharField(max_length=500)
    doi = models.CharField(max_length=200, null=True, blank=True)
    bibtex_original = models.TextField()
    metadata_completos = models.JSONField(null=True, blank=True)
    archivo_bib = models.CharField(
        max_length=255, 
        null=True, 
        blank=True, 
        help_text="Nombre del archivo .bib de origen"
    )
    archivo_pdf = models.FileField(
        upload_to=upload_pdf_to,
        null=True,
        blank=True,
        help_text="PDF del artículo guardado automáticamente desde DOI"
    )
    
    # 🆕 Control de Open Access
    es_open_access = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        help_text="¿Está disponible en Open Access? (Consultado desde Unpaywall API)"
    )
    url_open_access = models.URLField(
        null=True,
        blank=True,
        help_text="URL del PDF en Open Access (si está disponible)"
    )
    
    # Control de estado
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default='PENDIENTE'  # 🆕 CAMBIO: Ya no usa EN_ESPERA por defecto
    )
    
    # Control de duplicados
    articulo_original = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='duplicados'
    )
    
    # Fechas de control
    fecha_carga = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    fecha_asignacion = models.DateTimeField(
        null=True, 
        blank=True,
        help_text='Cuándo se asignaron tareas (ahora automático al crear)'
    )
    fecha_inicio_trabajo = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Cuándo el colaborador empezó a trabajar (EN_PROCESO)'
    )
    fecha_envio_revision = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Cuándo se envió a revisión'
    )
    fecha_aprobacion = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Cuándo fue aprobado'
    )

    class Meta:
        verbose_name = 'Artículo'
        verbose_name_plural = 'Artículos'
        ordering = ['-fecha_carga']
        indexes = [
            models.Index(fields=['proyecto', 'estado']),
            models.Index(fields=['usuario_asignado', 'estado']),
            models.Index(fields=['fecha_actualizacion']),
            models.Index(fields=['bibtex_key']),
        ]

    def __str__(self):
        return f"{self.titulo[:50]}... ({self.get_estado_display()})"
    
    def cambiar_estado(self, nuevo_estado, usuario=None):
        """Método centralizado para cambio de estados con validaciones"""
        estado_anterior = self.estado
        self.estado = nuevo_estado
        
        # Registrar fechas según el estado
        if nuevo_estado == 'PENDIENTE' and not self.fecha_asignacion:
            self.fecha_asignacion = timezone.now()
        elif nuevo_estado == 'EN_PROCESO' and not self.fecha_inicio_trabajo:
            self.fecha_inicio_trabajo = timezone.now()
        elif nuevo_estado == 'EN_REVISION':
            self.fecha_envio_revision = timezone.now()
        elif nuevo_estado == 'APROBADO':
            self.fecha_aprobacion = timezone.now()
        
        self.save()
        
        # Registrar en historial
        if usuario:
            HistorialArticulo.objects.create(
                articulo=self,
                usuario=usuario,
                tipo_cambio='CAMBIO_ESTADO',
                campo_modificado='estado',
                valor_anterior=estado_anterior,
                valor_nuevo=nuevo_estado
            )
        
        return True
    
    def porcentaje_completado(self):
        """Calcula el % de campos completados vs asignados"""
        campos_asignados = self.campos_asignados.all()
        if not campos_asignados.exists():
            return 0
        
        total = campos_asignados.count()
        completados = campos_asignados.filter(completado=True).count()
        
        return round((completados / total) * 100, 2) if total > 0 else 0
    
    def porcentaje_aprobado(self):
        """Calcula el % de campos aprobados vs completados"""
        campos_completados = self.campos_asignados.filter(completado=True)
        if not campos_completados.exists():
            return 0
        
        total = campos_completados.count()
        aprobados = campos_completados.filter(aprobado=True).count()
        
        return round((aprobados / total) * 100, 2) if total > 0 else 0
    
    def puede_aprobar_articulo(self):
        """Verifica si todos los campos completados están aprobados"""
        campos_completados = self.campos_asignados.filter(completado=True)
        if not campos_completados.exists():
            return False
        
        return not campos_completados.filter(aprobado=False).exists()


# ==================== 2. CAMPOMETANALISIS - SIN CAMBIOS ====================
# ✅ ESTÁ PERFECTO, no requiere modificaciones

class CampoMetanalisis(models.Model):
    """Catálogo de campos/variables que se pueden buscar en artículos"""
    
    CATEGORIA_CHOICES = [
        ('IDENTIFICACION', 'Identificación del Estudio'),
        ('METODOLOGIA', 'Metodología'),
        ('MUESTRA', 'Muestra y Participantes'),
        ('RESULTADOS', 'Resultados Estadísticos'),
        ('EFECTOS', 'Tamaños de Efecto'),
        ('CALIDAD', 'Calidad del Estudio'),
        ('OTROS', 'Otros'),
    ]
    
    TIPO_DATO_CHOICES = [
        ('TEXTO', 'Texto'),
        ('NUMERO', 'Número'),
        ('FECHA', 'Fecha'),
        ('SI_NO', 'Sí/No'),
        ('OPCIONES', 'Opciones múltiples'),
    ]
    
    nombre = models.CharField(
        max_length=200,
        unique=True,
        help_text='Nombre del campo (ej: "Tamaño de muestra")'
    )
    codigo = models.CharField(
        max_length=50,
        unique=True,
        help_text='Código corto para base de datos (ej: "sample_size")'
    )
    categoria = models.CharField(
        max_length=30,
        choices=CATEGORIA_CHOICES,
        default='OTROS'
    )
    tipo_dato = models.CharField(
        max_length=20,
        choices=TIPO_DATO_CHOICES,
        default='TEXTO'
    )
    descripcion = models.TextField(
        blank=True,
        help_text='Descripción detallada de qué buscar'
    )
    opciones_validas = models.JSONField(
        null=True,
        blank=True,
        help_text='Si tipo_dato=OPCIONES, lista de opciones válidas'
    )
    
    # Control
    es_predefinido = models.BooleanField(
        default=False,
        help_text='Campo del sistema (no se puede eliminar)'
    )
    proyecto = models.ForeignKey(
        Proyecto,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='campos_personalizados',
        help_text='Si es NULL, es global. Si tiene proyecto, es personalizado.'
    )
    creado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='campos_creados'
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Campo de Metaanálisis'
        verbose_name_plural = 'Campos de Metaanálisis'
        ordering = ['categoria', 'nombre']
        indexes = [
            models.Index(fields=['categoria', 'activo']),
            models.Index(fields=['proyecto']),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.get_categoria_display()})"


# ==================== 3. ASIGNACIONCAMPO - SIN CAMBIOS ====================
# ✅ ESTÁ PERFECTO con la aprobación granular

class AsignacionCampo(models.Model):
    """Relación entre artículo, colaborador y campo a buscar"""
    
    articulo = models.ForeignKey(
        Articulo,
        on_delete=models.CASCADE,
        related_name='campos_asignados'
    )
    campo = models.ForeignKey(
        CampoMetanalisis,
        on_delete=models.PROTECT,
        related_name='asignaciones'
    )
    
    valor = models.TextField(
        blank=True,
        null=True,
        help_text='Valor encontrado por el colaborador'
    )
    completado = models.BooleanField(
        default=False,
        help_text='Si el colaborador ya llenó este campo'
    )
    
    # Control de trabajo
    fecha_asignacion = models.DateTimeField(auto_now_add=True)
    fecha_completado = models.DateTimeField(null=True, blank=True)
    asignado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='campos_que_asigno'
    )
    
    # Aprobación granular por campo
    aprobado = models.BooleanField(
        default=False,
        help_text='Si este campo específico fue aprobado por un supervisor'
    )
    aprobado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='campos_aprobados',
        help_text='Supervisor que aprobó este campo específico'
    )
    fecha_aprobacion_campo = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Cuándo fue aprobado este campo'
    )
    
    notas = models.TextField(
        blank=True,
        help_text='Notas del colaborador sobre este campo específico'
    )

    class Meta:
        unique_together = ('articulo', 'campo')
        verbose_name = 'Asignación de Campo'
        verbose_name_plural = 'Asignaciones de Campos'
        ordering = ['campo__categoria', 'campo__nombre']
        indexes = [
            models.Index(fields=['articulo', 'completado']),
        ]

    def __str__(self):
        return f"{self.articulo.titulo[:30]}... - {self.campo.nombre}"
    
    def marcar_completado(self, valor, usuario=None):
        """Marca el campo como completado y guarda el valor"""
        self.valor = valor
        self.completado = bool(valor)
        self.fecha_completado = timezone.now() if valor else None
        self.save()
        
        if usuario:
            HistorialArticulo.objects.create(
                articulo=self.articulo,
                usuario=usuario,
                tipo_cambio='EDICION_METADATA',
                campo_modificado=self.campo.codigo,
                valor_nuevo=valor
            )
    
    def aprobar_campo(self, supervisor):
        """Aprueba este campo específico (aprobación granular)"""
        self.aprobado = True
        self.aprobado_por = supervisor
        self.fecha_aprobacion_campo = timezone.now()
        self.save()
        
        HistorialArticulo.objects.create(
            articulo=self.articulo,
            usuario=supervisor,
            tipo_cambio='APROBACION',
            campo_modificado=self.campo.codigo,
            valor_nuevo=f'Campo "{self.campo.nombre}" aprobado individualmente'
        )
    
    def desaprobar_campo(self, supervisor, razon=None):
        """Quita la aprobación de un campo (para correcciones)"""
        self.aprobado = False
        self.aprobado_por = None
        self.fecha_aprobacion_campo = None
        self.save()
        
        HistorialArticulo.objects.create(
            articulo=self.articulo,
            usuario=supervisor,
            tipo_cambio='SOLICITUD_CORRECCION',
            campo_modificado=self.campo.codigo,
            valor_nuevo=f'Aprobación retirada' + (f': {razon}' if razon else '')
        )


# ==================== 4. PLANTILLABUSQUEDA - CAMBIOS IMPORTANTES ====================
# 🆕 AGREGAR RESTRICCIÓN: Solo una plantilla predeterminada por proyecto

# ==================== PLANTILLAS DE ASIGNACIÓN ====================

class PlantillaBusqueda(models.Model):
    """
    🆕 CAMBIO: Ahora cada proyecto tiene UNA plantilla obligatoria
    que se aplica automáticamente a todos sus artículos
    """
    
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    proyecto = models.ForeignKey(
        Proyecto,
        on_delete=models.CASCADE,
        related_name='plantillas_busqueda'
    )
    campos = models.ManyToManyField(
        CampoMetanalisis,
        related_name='plantillas'
    )
    creado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    es_predeterminada = models.BooleanField(
        default=True,  # 🆕 CAMBIO: Ahora True por defecto
        help_text='Plantilla principal del proyecto (solo puede haber una)'
    )

    class Meta:
        verbose_name = 'Plantilla de Búsqueda'
        verbose_name_plural = 'Plantillas de Búsqueda'
        ordering = ['-es_predeterminada', 'nombre']
        # 🆕 AGREGAR RESTRICCIÓN ÚNICA
        constraints = [
            models.UniqueConstraint(
                fields=['proyecto', 'es_predeterminada'],
                condition=models.Q(es_predeterminada=True),
                name='una_plantilla_predeterminada_por_proyecto'
            )
        ]

    def __str__(self):
        predeterminada = " (Principal)" if self.es_predeterminada else ""
        return f"{self.nombre}{predeterminada} ({self.campos.count()} campos)"
    
    def save(self, *args, **kwargs):
        """
        🆕 SOBRESCRIBIR SAVE: Si se marca como predeterminada,
        desmarcar las demás del mismo proyecto
        """
        if self.es_predeterminada:
            PlantillaBusqueda.objects.filter(
                proyecto=self.proyecto,
                es_predeterminada=True
            ).exclude(pk=self.pk).update(es_predeterminada=False)
        
        super().save(*args, **kwargs)
    
    def aplicar_a_articulo(self, articulo, asignado_por):
        """Aplica todos los campos de la plantilla a un artículo"""
        campos_creados = []
        for campo in self.campos.all():
            asignacion, created = AsignacionCampo.objects.get_or_create(
                articulo=articulo,
                campo=campo,
                defaults={'asignado_por': asignado_por}
            )
            if created:
                campos_creados.append(asignacion)
        
        return campos_creados


# ==================== 5. COMENTARIOREVISION - SIN CAMBIOS ====================
# ✅ ESTÁ PERFECTO

class ComentarioRevision(models.Model):
    """Comentarios de supervisores durante el proceso de revisión"""
    
    TIPO_ACCION_CHOICES = [
        ('APROBADO', 'Aprobado'),
        ('CORRECCION', 'Corrección Solicitada'),
    ]
    
    articulo = models.ForeignKey(
        Articulo,
        on_delete=models.CASCADE,
        related_name='comentarios_revision'
    )
    supervisor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='comentarios_dados',
        help_text='Supervisor que hizo el comentario'
    )
    colaborador = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='comentarios_recibidos',
        help_text='Colaborador que recibe el comentario'
    )
    comentario = models.TextField()
    tipo_accion = models.CharField(
        max_length=20,
        choices=TIPO_ACCION_CHOICES
    )
    fecha_comentario = models.DateTimeField(auto_now_add=True)
    leido = models.BooleanField(
        default=False,
        help_text='Si el colaborador ya vio el comentario'
    )

    class Meta:
        ordering = ['-fecha_comentario']
        verbose_name = 'Comentario de Revisión'
        verbose_name_plural = 'Comentarios de Revisión'
        indexes = [
            models.Index(fields=['articulo', '-fecha_comentario']),
            models.Index(fields=['colaborador', 'leido']),
        ]

    def __str__(self):
        return f"{self.supervisor.username} -> {self.colaborador.username}: {self.tipo_accion}"


# ==================== 6. ARCHIVOSUBIDA - SIN CAMBIOS ====================
# ✅ ESTÁ PERFECTO

class ArchivoSubida(models.Model):
    """Archivos .bib subidos al proyecto"""
    
    proyecto = models.ForeignKey(
        Proyecto,
        on_delete=models.CASCADE,
        related_name='archivos_subidos'
    )
    usuario = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='archivos_subidos'
    )
    nombre_archivo = models.CharField(max_length=255)
    articulos_procesados = models.IntegerField(default=0)
    errores_procesamiento = models.JSONField(null=True, blank=True)
    fecha_subida = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Archivo Subido'
        verbose_name_plural = 'Archivos Subidos'
        ordering = ['-fecha_subida']
        indexes = [
            models.Index(fields=['proyecto', '-fecha_subida']),
        ]

    def __str__(self):
        return f"{self.nombre_archivo} ({self.proyecto.nombre})"


# ==================== 7. HISTORIALARTICULO - AGREGAR NUEVO TIPO ====================
# 🆕 AGREGAR nuevo tipo de cambio para asignación de plantilla

class HistorialArticulo(models.Model):
    """Historial completo de cambios en artículos"""
    
    TIPO_CAMBIO_CHOICES = [
        ('CREACION', 'Creación'),
        ('EDICION_METADATA', 'Edición de Metadata'),
        ('CAMBIO_ESTADO', 'Cambio de Estado'),
        ('ASIGNACION', 'Asignación de Tarea'),
        ('ASIGNACION_CAMPOS', 'Asignación de Campos'),  # 🆕 NUEVO
        ('DESASIGNACION_CAMPOS', 'Desasignación de Campos'),  # 🆕 NUEVO
        ('DESASIGNACION_CAMPO_INDIVIDUAL', 'Desasignación Individual'),  # 🆕 NUEVO
        ('MODIFICACION', 'Modificación'),
        ('DESCARGA', 'Descarga'),
        ('ELIMINACION', 'Eliminación'),
        ('ENVIO_REVISION', 'Envío a Revisión'),
        ('APROBACION', 'Aprobación'),
        ('SOLICITUD_CORRECCION', 'Corrección Solicitada'),
    ]
    
    articulo = models.ForeignKey(
        Articulo, 
        on_delete=models.CASCADE, 
        related_name='historial'
    )
    usuario = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='historial_articulos'
    )
    tipo_cambio = models.CharField(
        max_length=30,
        choices=TIPO_CAMBIO_CHOICES
    )
    campo_modificado = models.CharField(max_length=100, null=True, blank=True)
    valor_anterior = models.TextField(null=True, blank=True)
    valor_nuevo = models.TextField(null=True, blank=True)
    fecha_cambio = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Historial de Artículo'
        verbose_name_plural = 'Historial de Artículos'
        ordering = ['-fecha_cambio']
        indexes = [
            models.Index(fields=['articulo', '-fecha_cambio']),
            models.Index(fields=['tipo_cambio']),
            models.Index(fields=['usuario', '-fecha_cambio']),
        ]

    def __str__(self):
        fecha_str = self.fecha_cambio.strftime('%d/%m/%Y %H:%M')
        usuario_str = self.usuario.get_full_name() or self.usuario.username if self.usuario else 'Sistema'
        return f"{self.get_tipo_cambio_display()} - {self.articulo.titulo[:30]}... - {usuario_str} - {fecha_str}"


# ==================== 8. ANALISISARTICULO - NUEVO ====================
# 🆕 MODELO PARA GUARDAR ANÁLISIS CON IA

class AnalisisArticulo(models.Model):
    """
    Almacena los resultados del análisis IA de un artículo.
    Permite rastrear qué variables se buscaron y qué se encontró.
    """
    
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente de Análisis'),
        ('PROCESANDO', 'Procesando...'),
        ('COMPLETADO', 'Completado'),
        ('ERROR', 'Error en Análisis'),
    ]
    
    articulo = models.ForeignKey(
        Articulo,
        on_delete=models.CASCADE,
        related_name='analisis_ia'
    )
    proyecto = models.ForeignKey(
        Proyecto,
        on_delete=models.CASCADE,
        related_name='analisis_articulos'
    )
    
    # Variables analizadas
    campos_analizados = models.ManyToManyField(
        CampoMetanalisis,
        related_name='analisis',
        help_text='Campos que fueron buscados en el análisis'
    )
    
    # Resultados
    resultados = models.JSONField(
        help_text='JSON con estructura: {"campo_id": {"encontrado": bool, "contexto": str, "evidencia": str}}'
    )
    
    # Metadatos del análisis
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default='PENDIENTE'
    )
    tokens_utilizados = models.IntegerField(
        null=True,
        blank=True,
        help_text='Cantidad de tokens usados en la llamada a OpenAI'
    )
    costo_estimado = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text='Costo estimado en USD'
    )
    tiempo_procesamiento = models.IntegerField(
        null=True,
        blank=True,
        help_text='Tiempo en segundos'
    )
    
    # Auditoría
    analizado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='analisis_realizados'
    )
    fecha_analisis = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    # Errores
    mensaje_error = models.TextField(
        null=True,
        blank=True,
        help_text='Mensaje de error si algo falló'
    )
    
    # Validación manual (opcional)
    validado = models.BooleanField(
        default=False,
        help_text='Supervisor confirmó que los resultados son correctos'
    )
    notas_validacion = models.TextField(
        blank=True,
        help_text='Observaciones del supervisor tras revisar'
    )

    class Meta:
        verbose_name = 'Análisis de Artículo (IA)'
        verbose_name_plural = 'Análisis de Artículos (IA)'
        ordering = ['-fecha_analisis']
        indexes = [
            models.Index(fields=['articulo', '-fecha_analisis']),
            models.Index(fields=['proyecto', '-fecha_analisis']),
            models.Index(fields=['estado']),
        ]

    def __str__(self):
        estado_icon = {
            'PENDIENTE': '⏳',
            'PROCESANDO': '⚙️',
            'COMPLETADO': '✅',
            'ERROR': '❌',
        }
        return f"{estado_icon.get(self.estado, '?')} {self.articulo.titulo[:40]}... ({self.get_estado_display()})"