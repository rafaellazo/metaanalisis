# articulos/urls.py

from django.urls import path
from . import views

app_name = 'articulos'

urlpatterns = [

    # ==================== GESTIÓN DE ARTÍCULOS ====================
    path('<int:proyecto_id>/',
         views.ver_articulos,
         name='ver_articulos'),

    path('<int:proyecto_id>/agregar/',
         views.agregar_articulo,
         name='agregar_articulo'),

    path('<int:proyecto_id>/subir/',
         views.subir_archivo,
         name='subir_archivo'),

    path('visualizar/<int:archivo_id>/',
         views.visualizar_articulos,
         name='visualizar_articulos'),

    # ==================== WORKSPACE Y TRABAJO EN ARTÍCULOS ====================
    path('workspace/<int:articulo_id>/',
         views.workspace_articulo,
         name='workspace_articulo'),
    
    path('workspace/<int:articulo_id>/guardar-campo/',
         views.guardar_campo_workspace,
         name='guardar_campo_workspace'),
    
    path('articulo/<int:articulo_id>/sugerencias-analisis/', 
         views.obtener_sugerencias_analisis, 
         name='sugerencias_analisis'),

    path('workspace/<int:articulo_id>/guardar-pdf/',
         views.guardar_pdf_doi,
         name='guardar_pdf_doi'),

    # ==================== PLANTILLA DEL PROYECTO (NUEVO SISTEMA) ====================
    path('proyecto/<int:proyecto_id>/plantilla/editar/',
         views.editar_plantilla_proyecto,
         name='editar_plantilla_proyecto'),

    path('proyecto/<int:proyecto_id>/variables/',
         views.gestionar_variables_globales,
         name='gestionar_variables_globales'),

    # ==================== GESTIÓN DE CAMPOS PERSONALIZADOS ====================
    path('proyecto/<int:proyecto_id>/campos/',
         views.gestionar_campos,
         name='gestionar_campos'),

    path('campo/<int:campo_id>/eliminar/',
         views.eliminar_campo,
         name='eliminar_campo'),

    # ==================== REVISIÓN Y APROBACIÓN ====================
    path('proyecto/<int:proyecto_id>/bandeja-revision/',
         views.bandeja_revision,
         name='bandeja_revision'),

    path('articulo/<int:articulo_id>/enviar-revision/',
         views.enviar_a_revision,
         name='enviar_a_revision'),

    path('proyecto/<int:proyecto_id>/enviar-masivo-revision/',
         views.enviar_masivo_revision,
         name='enviar_masivo_revision'),

    path('articulo/<int:articulo_id>/aprobar/',
         views.aprobar_articulo,
         name='aprobar_articulo'),

    path('articulo/<int:articulo_id>/solicitar-correccion/',
         views.solicitar_correccion,
         name='solicitar_correccion'),

    # ==================== APROBACIÓN DE CAMPOS INDIVIDUALES ====================
    path('campo/<int:asignacion_id>/aprobar/',
         views.aprobar_campo_individual,
         name='aprobar_campo_individual'),

    path('campo/<int:asignacion_id>/solicitar-correccion/',
         views.solicitar_correccion_campo,
         name='solicitar_correccion_campo'),

    # ==================== DESCARGA Y ELIMINACIÓN ====================
    path('descargar/<int:articulo_id>/',
         views.descargar_articulo,
         name='descargar_articulo'),

    path('descargar-pdf/<int:articulo_id>/',
         views.descargar_pdf,
         name='descargar_pdf'),

    path('visualizar-pdf/<int:articulo_id>/',
         views.visualizar_pdf,
         name='visualizar_pdf'),

    path('eliminar-pdf/<int:articulo_id>/',
         views.eliminar_pdf,
         name='eliminar_pdf'),

    path('eliminar/<int:articulo_id>/',
         views.eliminar_articulo,
         name='eliminar_articulo'),

    path('descargar-archivo/<str:archivo_nombre>/',
         views.descargar_archivo_bib,
         name='descargar_archivo_bib'),

    path('descargar-pdf/<int:articulo_id>/',
         views.descargar_pdf_doi,
         name='descargar_pdf_doi'),

    path('guardar-pdf/<int:articulo_id>/',
         views.guardar_pdf_doi,
         name='guardar_pdf_doi'),

    # ==================== EXPORTACIÓN A EXCEL ====================
    path('articulo/<int:articulo_id>/generar-excel/',
         views.generar_excel_articulo,
         name='generar_excel_articulo'),

    path('proyecto/<int:proyecto_id>/generar-excel-general/',
         views.generar_excel_proyecto,
         name='generar_excel_proyecto'),

    # Página para seleccionar artículos y descargar Excel individuales (multiple)
    path('proyecto/<int:proyecto_id>/descargas/seleccionar/',
         views.seleccionar_descarga,
         name='seleccionar_descarga'),

    # ==================== ESTADÍSTICAS Y ANÁLISIS ====================
    path('<int:proyecto_id>/mi-progreso/',
         views.mi_progreso,
         name='mi_progreso'),

    path('<int:proyecto_id>/estadisticas/',
         views.estadisticas_proyecto,
         name='estadisticas_proyecto'),

    path('<int:proyecto_id>/estadisticas/usuarios/',
         views.estadisticas_por_usuario,
         name='estadisticas_por_usuario'),

    path('<int:proyecto_id>/estadisticas/exportar/',
         views.exportar_estadisticas_json,
         name='exportar_estadisticas'),

    # ==================== ESTADÍSTICAS DE ARTÍCULO ====================
    path('workspace/<int:articulo_id>/estadisticas/',
         views.estadisticas_articulo,
         name='estadisticas_articulo'),

    # ==================== FOREST PLOT ====================
    path('proyecto/<int:proyecto_id>/panel-forest-plot/',
         views.panel_forest_plot,
         name='panel_forest_plot'),

    path('proyecto/<int:proyecto_id>/filtrar-forest-plot/',
         views.filtrar_forest_plot,
         name='filtrar_forest_plot'),

    path('proyecto/<int:proyecto_id>/generar-forest-plot/',
         views.generar_forest_plot,
         name='generar_forest_plot'),

    # ==================== PCA ====================
    path('proyecto/<int:proyecto_id>/panel-pca/',
         views.panel_pca,
         name='panel_pca'),

    path('proyecto/<int:proyecto_id>/filtrar-pca/',
         views.filtrar_pca,
         name='filtrar_pca'),

    path('proyecto/<int:proyecto_id>/exportar-clusters-pca/',
         views.exportar_clusters_pca,
         name='exportar_clusters_pca'),

    path('proyecto/<int:proyecto_id>/exportar-coordenadas-biplot/',
         views.exportar_coordenadas_biplot,
         name='exportar_coordenadas_biplot'),

    # ==================== ANÁLISIS DE ARTÍCULOS CON IA ====================
    path('articulo/<int:articulo_id>/analizar/',
         views.analizar_articulo_view,
         name='analizar_articulo'),

    path('analisis/<int:analisis_id>/resultados/',
         views.ver_resultados_analisis,
         name='ver_resultados_analisis'),

    path('proyecto/<int:proyecto_id>/analisis/',
         views.listar_analisis_proyecto,
         name='listar_analisis_proyecto'),

]