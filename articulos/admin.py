from django.contrib import admin
from .models import (
    AlertaSaldo, AnalisisArticulo, Articulo, CalibracionSaldo, EstadoSincronizacion,
    GastoOpenAI, RegistroConsumoIA,
)

@admin.register(Articulo)
class ArticuloAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'proyecto', 'usuario_carga', 'estado', 'fecha_carga')
    list_filter = ('estado', 'proyecto', 'usuario_carga', 'fecha_carga')
    search_fields = ('titulo', 'bibtex_key', 'doi')
    readonly_fields = ('fecha_carga',)
    ordering = ('-fecha_carga',)


@admin.register(RegistroConsumoIA)
class RegistroConsumoIAAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'articulo_titulo', 'proyecto_nombre', 'modelo', 'costo_usd', 'exito')
    list_filter = ('tipo_operacion', 'exito', 'modelo', 'fecha')
    search_fields = ('articulo_titulo', 'archivo_bib', 'proyecto_nombre')
    readonly_fields = [field.name for field in RegistroConsumoIA._meta.fields]

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(CalibracionSaldo)
class CalibracionSaldoAdmin(admin.ModelAdmin):
    list_display = ('fecha_calibracion', 'saldo_base', 'registrado_por')


admin.site.register(GastoOpenAI)
admin.site.register(EstadoSincronizacion)
admin.site.register(AlertaSaldo)