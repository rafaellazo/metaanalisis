from django.contrib import admin
from .models import Articulo

@admin.register(Articulo)
class ArticuloAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'proyecto', 'usuario_carga', 'estado', 'fecha_carga')
    list_filter = ('estado', 'proyecto', 'usuario_carga', 'fecha_carga')
    search_fields = ('titulo', 'bibtex_key', 'doi')
    readonly_fields = ('fecha_carga',)
    ordering = ('-fecha_carga',)