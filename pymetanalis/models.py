from django.db import models
from django.contrib.auth.models import User

class Proyecto(models.Model):
    ESTADO_CHOICES = [
        ('ACTIVO', 'Activo'),
        ('PAUSADO', 'Pausado'),
        ('FINALIZADO', 'Finalizado'),
    ]
    
    CATEGORIA_CHOICES = [
        ('SALUD', 'Salud'),
        ('TECNOLOGIA', 'Tecnología'),
        ('EDUCACION', 'Educación'),
        ('CIENCIAS_SOCIALES', 'Ciencias Sociales'),
        ('INGENIERIA', 'Ingeniería'),
    ]

    nombre = models.CharField(max_length=255)
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES, default='SALUD')
    usuario_creador = models.ForeignKey(User, on_delete=models.PROTECT, related_name='proyectos_creados')
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='ACTIVO')
    configuracion = models.JSONField(null=True, blank=True)
    total_articulos = models.IntegerField(default=0)
    articulos_trabajados = models.IntegerField(default=0)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Proyecto'
        verbose_name_plural = 'Proyectos'

    def __str__(self):
        return self.nombre

class UsuarioProyecto(models.Model):
    ROL_PROYECTO_CHOICES = [
        ('DUEÑO', 'Dueño'),
        ('SUPERVISOR', 'Supervisor'),
        ('COLABORADOR', 'Colaborador'),
    ]

    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='usuario_proyectos')
    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, related_name='usuario_proyectos')
    rol_proyecto = models.CharField(max_length=20, choices=ROL_PROYECTO_CHOICES)
    fecha_incorporacion = models.DateTimeField(auto_now_add=True)
    puede_invitar = models.BooleanField(default=False)

    class Meta:
        unique_together = ('usuario', 'proyecto')
        verbose_name = 'Usuario Proyecto'
        verbose_name_plural = 'Usuarios Proyectos'

    def __str__(self):
        return f"{self.usuario.username} - {self.proyecto.nombre} ({self.rol_proyecto})"

class SolicitudProyecto(models.Model):
    TIPO_SOLICITUD_CHOICES = [
        ('UNIRSE', 'Solicitud para unirse'),
        ('CAMBIO_ROL', 'Solicitud de cambio de rol'),
    ]
    
    ESTADO_SOLICITUD_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('APROBADA', 'Aprobada'),
        ('RECHAZADA', 'Rechazada'),
    ]

    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='solicitudes_proyecto')
    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, related_name='solicitudes')
    tipo_solicitud = models.CharField(max_length=20, choices=TIPO_SOLICITUD_CHOICES)
    estado = models.CharField(max_length=20, choices=ESTADO_SOLICITUD_CHOICES, default='PENDIENTE')
    mensaje = models.TextField(blank=True, null=True)
    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    fecha_respuesta = models.DateTimeField(blank=True, null=True)
    respondido_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='solicitudes_respondidas')

    class Meta:
        verbose_name = 'Solicitud Proyecto'
        verbose_name_plural = 'Solicitudes Proyectos'
        ordering = ['-fecha_solicitud']

    def __str__(self):
        return f"{self.usuario.username} - {self.proyecto.nombre} ({self.tipo_solicitud})"

class EstadisticaProyecto(models.Model):
    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, related_name='estadisticas')
    fecha = models.DateField()
    total_articulos = models.IntegerField(default=0)
    articulos_aprobados = models.IntegerField(default=0)
    promedio_calidad = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = ('proyecto', 'fecha')
        verbose_name = 'Estadística Proyecto'
        verbose_name_plural = 'Estadísticas Proyectos'
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.proyecto.nombre} - {self.fecha}"
class Notificacion(models.Model):
    TIPO_CHOICES = [
        ('solicitud_aceptada', 'Solicitud Aceptada'),
        ('solicitud_rechazada', 'Solicitud Rechazada'),
        ('invitacion_proyecto', 'Invitación a Proyecto'),
        ('nueva_solicitud', 'Nueva Solicitud'),  # ← Esta es la que necesitas
        ('cambio_rol', 'Cambio de Rol'),
        ('general', 'General'),
    ]
    
    usuario = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='notificaciones',
        help_text='Usuario que recibe la notificación'
    )
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    titulo = models.CharField(max_length=255)
    mensaje = models.TextField()
    leida = models.BooleanField(default=False)
    url = models.CharField(max_length=500, blank=True, null=True)
    
    # Relaciones opcionales para contexto
    proyecto = models.ForeignKey(
        Proyecto, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='notificaciones'
    )
    solicitud = models.ForeignKey(
        SolicitudProyecto,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notificaciones'
    )
    
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_lectura = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Notificación'
        verbose_name_plural = 'Notificaciones'
        ordering = ['-fecha_creacion']
        indexes = [
            models.Index(fields=['usuario', 'leida', '-fecha_creacion']),
        ]
    
    def __str__(self):
        return f"{self.usuario.username} - {self.get_tipo_display()} - {'Leída' if self.leida else 'No leída'}"
    
    def marcar_como_leida(self):
        """Marca la notificación como leída"""
        if not self.leida:
            from django.utils import timezone
            self.leida = True
            self.fecha_lectura = timezone.now()
            self.save(update_fields=['leida', 'fecha_lectura'])
class Invitacion(models.Model):
    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, related_name='invitaciones')
    email_destino = models.EmailField()
    token = models.CharField(max_length=100, unique=True)
    creado_por = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invitaciones_enviadas')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_aceptacion = models.DateTimeField(null=True, blank=True)
    aceptado = models.BooleanField(default=False)

    def __str__(self):
        return f"Invitación a {self.email_destino} para {self.proyecto.nombre}"