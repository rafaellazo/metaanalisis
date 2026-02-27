from django.contrib import admin
from .models import Proyecto, UsuarioProyecto, EstadisticaProyecto,Notificacion

admin.site.register(Proyecto)
admin.site.register(UsuarioProyecto)
admin.site.register(EstadisticaProyecto)
@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'tipo', 'titulo', 'leida', 'fecha_creacion')
    list_filter = ('tipo', 'leida', 'fecha_creacion')
    search_fields = ('usuario__username', 'titulo', 'mensaje')
    readonly_fields = ('fecha_creacion', 'fecha_lectura')