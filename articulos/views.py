# ARTICULOS VIEWS CON SISTEMA DE NOTIFICACIONES INTEGRADO

# Imports de Python estándar
import json
import zipfile
from datetime import timedelta
from io import BytesIO

# Imports de terceros
import bibtexparser
import numpy as np
import openpyxl
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import requests
from bibtexparser.bparser import BibTexParser
from openpyxl.styles import Font, PatternFill, Alignment
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

# Imports de Django
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q, Count, Prefetch, Avg, Sum, Case, When, IntegerField
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.core.paginator import Paginator

# Imports locales
from pymetanalis.models import Proyecto, UsuarioProyecto, Notificacion
from .models import (
    Articulo, ArchivoSubida, HistorialArticulo,
    CampoMetanalisis, AsignacionCampo, PlantillaBusqueda, ComentarioRevision, AnalisisArticulo
)
from .utils import obtener_pdf_desde_doi, consultar_open_access_unpaywall

# ==================== FUNCIÓN HELPER PARA NOTIFICACIONES ====================

def crear_notificacion_articulos(usuario, tipo, titulo, mensaje, url=None, proyecto=None):
    """Helper para crear notificaciones relacionadas con artículos"""
    try:
        Notificacion.objects.create(
            usuario=usuario,
            tipo=tipo,
            titulo=titulo,
            mensaje=mensaje,
            url=url,
            proyecto=proyecto
        )
    except Exception as e:
        print(f"Error creando notificación: {e}")


# 🆕 ==================== FUNCIÓN HELPER PARA CONSULTAR OPEN ACCESS ====================

def actualizar_open_access_articulo(articulo):
    """
    Consulta Unpaywall API para actualizar el estado de Open Access de un artículo.
    Guarda el resultado en los campos es_open_access y url_open_access.
    """
    if not articulo.doi and not articulo.bibtex_key:
        return False
    
    try:
        # Obtener DOI del artículo (desde metadata o campo directo)
        doi = articulo.doi
        if not doi and articulo.metadata_completos:
            doi = articulo.metadata_completos.get('doi')
        
        if not doi:
            return False
        
        # Consultar Unpaywall
        resultado = consultar_open_access_unpaywall(doi)
        
        if resultado['error'] is None:
            articulo.es_open_access = resultado['es_open_access']
            articulo.url_open_access = resultado['url_pdf']
            articulo.save(update_fields=['es_open_access', 'url_open_access'])
            return True
        
        return False
    
    except Exception as e:
        print(f"Error actualizando open access para {articulo.id}: {e}")
        return False


# ==================== VISUALIZACIÓN DE ARTÍCULOS ====================


def aplicar_plantilla_proyecto_a_articulo(articulo, usuario=None):
    """
    🎯 Aplica automáticamente la plantilla del proyecto a un artículo
    Retorna la cantidad de campos asignados
    """
    proyecto = articulo.proyecto
    
    # Obtener la plantilla del proyecto
    plantilla = PlantillaBusqueda.objects.filter(
        proyecto=proyecto,
        es_predeterminada=True
    ).first()
    
    if not plantilla:
        print(f"⚠️ El proyecto {proyecto.nombre} no tiene plantilla predeterminada")
        return 0
    
    campos_asignados = 0
    
    for campo in plantilla.campos.all():
        # Verificar si ya existe
        if not AsignacionCampo.objects.filter(articulo=articulo, campo=campo).exists():
            AsignacionCampo.objects.create(
                articulo=articulo,
                campo=campo,
                asignado_por=usuario
            )
            campos_asignados += 1
    
    return campos_asignados

@login_required
def ver_articulos(request, proyecto_id):
    """Vista para ver los artículos de un proyecto, con lógica diferenciada por rol."""
    try:
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    except (Proyecto.DoesNotExist, ValueError):
        messages.error(request, 'Proyecto no encontrado.')
        return redirect('mis_proyectos')

    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto
    ).first()
    if not usuario_proyecto:
        messages.error(request, 'No tienes acceso a este proyecto.')
        return redirect('mis_proyectos')

    request.session['proyecto_actual_id'] = proyecto.id
    request.session.modified = True

    if 'archivos_sesion' in request.session:
        try:
            del request.session['archivos_sesion']
        except KeyError:
            pass

    # Filtros
    estado_filtro = request.GET.get('estado', '')
    usuario_filtro = request.GET.get('usuario', '')

    # Query base
    articulos_base = Articulo.objects.filter(proyecto=proyecto)

    if estado_filtro:
        articulos_base = articulos_base.filter(estado=estado_filtro)
    if usuario_filtro:
        articulos_base = articulos_base.filter(
            Q(usuario_asignado_id=usuario_filtro) | Q(usuario_carga_id=usuario_filtro)
        )

    articulos_base = articulos_base.order_by('-fecha_carga')

    # Obtener colaboradores (para filtro y dueño)
    colaboradores = UsuarioProyecto.objects.filter(
        proyecto=proyecto
    ).select_related('usuario').order_by('usuario__first_name', 'usuario__username')

    # ================================
    # LÓGICA POR ROL
    # ================================

    if usuario_proyecto.rol_proyecto == 'DUEÑO':
        # Agrupar artículos por colaborador (usuario_carga)
        articulos_por_colaborador = {}
        for up in colaboradores:
            usuario = up.usuario
            articulos_usuario = articulos_base.filter(usuario_carga=usuario)
            if articulos_usuario.exists():
                con_bib = articulos_usuario.exclude(Q(archivo_bib__isnull=True) | Q(archivo_bib=''))
                sin_bib = articulos_usuario.filter(Q(archivo_bib__isnull=True) | Q(archivo_bib=''))
                con_pdf = articulos_usuario.exclude(Q(archivo_pdf__isnull=True) | Q(archivo_pdf=''))
                articulos_por_colaborador[usuario] = {
                    'articulos': articulos_usuario,
                    'con_bib': con_bib,
                    'sin_bib': sin_bib,
                    'con_pdf': con_pdf,
                }

        # Estadísticas generales (sin filtro)
        total_articulos = Articulo.objects.filter(proyecto=proyecto).count()
        articulos_en_espera = Articulo.objects.filter(proyecto=proyecto, estado='EN_ESPERA').count()
        articulos_pendientes = Articulo.objects.filter(proyecto=proyecto, estado='PENDIENTE').count()
        articulos_en_proceso = Articulo.objects.filter(proyecto=proyecto, estado='EN_PROCESO').count()
        articulos_en_revision = Articulo.objects.filter(proyecto=proyecto, estado='EN_REVISION').count()
        articulos_aprobados = Articulo.objects.filter(proyecto=proyecto, estado='APROBADO').count()

        # Calcular artículos con/sin BIB y con PDF (para que DUEÑO vea las mismas secciones)
        articulos_con_bib = articulos_base.exclude(Q(archivo_bib__isnull=True) | Q(archivo_bib=''))
        articulos_sin_bib = articulos_base.filter(Q(archivo_bib__isnull=True) | Q(archivo_bib=''))
        articulos_con_pdf = articulos_base.exclude(Q(archivo_pdf__isnull=True) | Q(archivo_pdf=''))

        context = {
            'proyecto': proyecto,
            'usuario_proyecto': usuario_proyecto,
            'colaboradores': colaboradores,
            'articulos_por_colaborador': articulos_por_colaborador,
            'articulos': articulos_base,
            'articulos_con_bib': articulos_con_bib,
            'articulos_sin_bib': articulos_sin_bib,
            'articulos_con_pdf': articulos_con_pdf,
            'es_dueño': True,
            # Estadísticas
            'total_articulos': total_articulos,
            'articulos_en_espera': articulos_en_espera,
            'articulos_pendientes': articulos_pendientes,
            'articulos_en_proceso': articulos_en_proceso,
            'articulos_en_revision': articulos_en_revision,
            'articulos_aprobados': articulos_aprobados,
            # Filtros actuales
            'estado_filtro': estado_filtro,
            'usuario_filtro': usuario_filtro,
        }

    else:  # COLABORADOR
        articulos = articulos_base.filter(
            Q(usuario_carga=request.user) | Q(usuario_asignado=request.user)
        )

        articulos_con_bib = articulos.exclude(Q(archivo_bib__isnull=True) | Q(archivo_bib=''))
        articulos_sin_bib = articulos.filter(Q(archivo_bib__isnull=True) | Q(archivo_bib=''))
        articulos_con_pdf = articulos.exclude(Q(archivo_pdf__isnull=True) | Q(archivo_pdf=''))

        total_articulos = articulos.count()
        articulos_en_espera = articulos.filter(estado='EN_ESPERA').count()
        articulos_pendientes = articulos.filter(estado='PENDIENTE').count()
        articulos_en_proceso = articulos.filter(estado='EN_PROCESO').count()
        articulos_en_revision = articulos.filter(estado='EN_REVISION').count()
        articulos_aprobados = articulos.filter(estado='APROBADO').count()

        context = {
            'proyecto': proyecto,
            'usuario_proyecto': usuario_proyecto,
            'articulos': articulos,
            'articulos_con_bib': articulos_con_bib,
            'articulos_sin_bib': articulos_sin_bib,
            'articulos_con_pdf': articulos_con_pdf,
            'es_dueño': False,
            # Estadísticas
            'total_articulos': total_articulos,
            'articulos_en_espera': articulos_en_espera,
            'articulos_pendientes': articulos_pendientes,
            'articulos_en_proceso': articulos_en_proceso,
            'articulos_en_revision': articulos_en_revision,
            'articulos_aprobados': articulos_aprobados,
            # Filtros actuales
            'estado_filtro': estado_filtro,
            'usuario_filtro': usuario_filtro,
            'colaboradores': colaboradores,
        }

    return render(request, 'ver_articulos.html', context)

@login_required
def visualizar_articulos(request, archivo_id):
    """Vista para mostrar todos los artículos de un archivo .bib subido"""
    archivo = get_object_or_404(ArchivoSubida, id=archivo_id)
    
    # Verificar acceso
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=archivo.proyecto
    ).first()
    
    if not usuario_proyecto:
        messages.error(request, 'No tienes acceso a este proyecto.')
        return redirect('mis_proyectos')
    
    # Obtener todos los artículos asociados a este archivo específico
    articulos = Articulo.objects.filter(
        proyecto=archivo.proyecto,
        archivo_bib=archivo.nombre_archivo
    ).order_by('-fecha_carga')
    
    return render(request, 'visualizar_articulos.html', {
        'archivo': archivo,
        'articulos': articulos,
        'proyecto': archivo.proyecto
    })


# ==================== DESCARGAS ====================

@login_required
def descargar_articulo(request, articulo_id):
    """Vista para descargar el PDF o BibTeX de un artículo individual."""
    articulo = get_object_or_404(Articulo, id=articulo_id)
    
    # Verificar acceso
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=articulo.proyecto
    ).first()
    
    if not usuario_proyecto:
        messages.error(request, 'No tienes permiso para acceder a este artículo.')
        return redirect('mis_proyectos')
    
    # Si tiene PDF guardado, devolver el PDF
    if articulo.archivo_pdf:
        try:
            # Leer el archivo PDF
            with articulo.archivo_pdf.open('rb') as pdf_file:
                pdf_content = pdf_file.read()
            
            # Crear respuesta HTTP con el PDF
            response = HttpResponse(pdf_content, content_type='application/pdf')
            filename = articulo.archivo_pdf.name.split('/')[-1]  # Obtener solo el nombre del archivo
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            response['Content-Length'] = len(pdf_content)
            
            # Registrar descarga en historial
            HistorialArticulo.objects.create(
                articulo=articulo,
                usuario=request.user,
                tipo_cambio='DESCARGA',
                valor_nuevo=f'PDF descargado: {filename}'
            )
            
            return response
            
        except Exception as e:
            messages.error(request, f'Error al descargar el PDF: {str(e)}')
            return redirect('articulos:workspace_articulo', articulo_id=articulo.id)
    
    # Si no tiene PDF, devolver el BibTeX
    bibtex_content = articulo.bibtex_original
    
    # Crear respuesta HTTP
    response = HttpResponse(bibtex_content, content_type='application/x-bibtex')
    nombre_archivo = f"{articulo.bibtex_key}.bib"
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    
    # Registrar descarga en historial
    HistorialArticulo.objects.create(
        articulo=articulo,
        usuario=request.user,
        tipo_cambio='DESCARGA',
        valor_nuevo=f'Archivo BibTeX descargado'
    )
    
    return response


@login_required
def descargar_archivo_bib(request, archivo_nombre):
    """Vista para descargar un archivo .bib completo con todos sus artículos."""
    proyecto_id = request.GET.get('proyecto_id')
    
    if not proyecto_id:
        messages.error(request, 'Proyecto no especificado.')
        return redirect('mis_proyectos')
    
    try:
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    except (Proyecto.DoesNotExist, ValueError):
        messages.error(request, 'Proyecto no encontrado.')
        return redirect('mis_proyectos')
    
    # Verificar acceso
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto
    ).first()
    
    if not usuario_proyecto:
        messages.error(request, 'No tienes permiso para acceder a este proyecto.')
        return redirect('mis_proyectos')
    
    # Obtener artículos del archivo
    articulos = Articulo.objects.filter(
        proyecto=proyecto,
        archivo_bib=archivo_nombre
    ).order_by('bibtex_key')
    
    if not articulos.exists():
        messages.error(request, 'No se encontraron artículos para este archivo.')
        return redirect('articulos:ver_articulos', proyecto_id=proyecto.id)
    
    # Generar contenido BibTeX completo
    bibtex_content = ""
    for articulo in articulos:
        bibtex_content += articulo.bibtex_original + "\n\n"
    
    # Crear respuesta HTTP
    response = HttpResponse(bibtex_content, content_type='application/x-bibtex')
    response['Content-Disposition'] = f'attachment; filename="{archivo_nombre}"'
    
    return response


@login_required
def descargar_pdf_doi(request, articulo_id):
    """
    Vista para descargar PDF de un artículo usando su DOI.
    Busca versiones open access automáticamente.
    """
    try:
        articulo = get_object_or_404(Articulo, id=articulo_id)
    except (Articulo.DoesNotExist, ValueError):
        messages.error(request, 'Artículo no encontrado.')
        return redirect('mis_proyectos')

    # Verificar acceso al proyecto
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=articulo.proyecto
    ).first()

    if not usuario_proyecto:
        messages.error(request, 'No tienes permiso para acceder a este artículo.')
        return redirect('mis_proyectos')

    # Verificar que tenga DOI
    doi = articulo.doi
    if not doi:
        messages.error(request, 'Este artículo no tiene DOI registrado.')
        return redirect('articulos:workspace_articulo', articulo_id=articulo.id)

    # Importar función de utils
    from .utils import obtener_pdf_desde_doi

    # Buscar PDF
    resultado = obtener_pdf_desde_doi(doi)

    if resultado['success'] and resultado['pdf_url']:
        pdf_url = resultado['pdf_url']

        try:
            # Intentar descargar el PDF directamente (sin verificación previa)
            pdf_response = requests.get(pdf_url, timeout=60, stream=False)
            pdf_response.raise_for_status()

            # Verificar que sea realmente un PDF
            content_type = pdf_response.headers.get('content-type', '').lower()
            if 'pdf' not in content_type and 'application/pdf' not in content_type:
                # Si no es PDF, redirigir a la URL externa
                return redirect(pdf_url)

            # Crear nombre de archivo
            titulo_limpio = "".join(c for c in articulo.titulo if c.isalnum() or c in (' ', '-', '_')).rstrip()
            if not titulo_limpio:
                titulo_limpio = f"articulo_{articulo.id}"
            filename = f"{titulo_limpio[:50]}.pdf"

            # Crear respuesta HTTP con el PDF
            response = HttpResponse(
                pdf_response.content,
                content_type='application/pdf'
            )
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            response['Content-Length'] = len(pdf_response.content)

            return response

        except requests.RequestException as e:
            # Si hay error en la descarga, redirigir a la URL externa
            return redirect(pdf_url)
    else:
        # Mostrar mensaje con opciones alternativas
        error_msg = 'No se encontró una versión open access de este artículo. '
        error_msg += 'Puedes intentar acceder directamente desde el DOI o buscar en otras fuentes.'

        messages.warning(request, error_msg)
        return redirect('articulos:workspace_articulo', articulo_id=articulo.id)


@login_required
def guardar_pdf_doi(request, articulo_id):
    """Vista para guardar automáticamente el PDF de un artículo desde su DOI"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        articulo = get_object_or_404(Articulo, id=articulo_id)
        
        # Verificar acceso al proyecto
        usuario_proyecto = UsuarioProyecto.objects.filter(
            usuario=request.user,
            proyecto=articulo.proyecto
        ).first()
        
        if not usuario_proyecto:
            return JsonResponse({'error': 'No tienes acceso a este artículo'}, status=403)
        
        # Verificar que el artículo tenga DOI
        if not articulo.doi:
            return JsonResponse({'error': 'El artículo no tiene DOI'}, status=400)
        
        # Verificar que no tenga ya un PDF guardado
        if articulo.archivo_pdf:
            return JsonResponse({'error': 'El artículo ya tiene un PDF guardado'}, status=400)
        
        # Intentar descargar el PDF
        from .utils import obtener_pdf_desde_doi
        resultado = obtener_pdf_desde_doi(articulo.doi)
        
        if not resultado.get('success', False) or not resultado.get('pdf_url'):
            return JsonResponse({
                'error': 'No se encontró una versión open access del artículo'
            }, status=404)
        
        pdf_url = resultado['pdf_url']
        
        # Descargar el PDF
        import requests
        from django.core.files.base import ContentFile
        
        try:
            pdf_response = requests.get(pdf_url, timeout=60, stream=True)
            pdf_response.raise_for_status()
            
            # Verificar que sea realmente un PDF
            content_type = pdf_response.headers.get('content-type', '').lower()
            if 'pdf' not in content_type and 'application/pdf' not in content_type:
                return JsonResponse({'error': 'La URL no contiene un archivo PDF válido'}, status=400)
            
            # Crear nombre de archivo
            titulo_limpio = "".join(c for c in articulo.titulo if c.isalnum() or c in (' ', '-', '_')).rstrip()
            if not titulo_limpio:
                titulo_limpio = f"articulo_{articulo.id}"
            filename = f"{titulo_limpio[:50]}.pdf"
            
            # Guardar el archivo en el modelo
            articulo.archivo_pdf.save(filename, ContentFile(pdf_response.content), save=True)
            
            # Registrar en historial
            HistorialArticulo.objects.create(
                articulo=articulo,
                usuario=request.user,
                tipo_cambio='MODIFICACION',
                campo_modificado='archivo_pdf',
                valor_nuevo=f'PDF guardado automáticamente desde DOI: {articulo.doi}'
            )
            
            return JsonResponse({
                'success': True,
                'message': 'PDF guardado correctamente',
                'filename': filename
            })
            
        except requests.RequestException as e:
            return JsonResponse({
                'error': f'Error al descargar el PDF: {str(e)}'
            }, status=500)
            
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return JsonResponse({
            'error': f'Error interno del servidor: {str(e)}',
            'traceback': error_details
        }, status=500)


# ==================== GESTIÓN DE ARTÍCULOS ====================

@login_required
def agregar_articulo(request, proyecto_id):
    """
    🆕 MODIFICADA: Guarda todos los campos del formulario manual en metadata_completos
    """
    try:
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    except (Proyecto.DoesNotExist, ValueError):
        messages.error(request, 'Proyecto no encontrado.')
        return redirect('mis_proyectos')
    
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto
    ).first()
    
    if not usuario_proyecto:
        messages.error(request, 'No tienes permiso para agregar artículos a este proyecto.')
        return redirect('mis_proyectos')
    
    # 🆕 VERIFICAR PLANTILLA
    plantilla = PlantillaBusqueda.objects.filter(
        proyecto=proyecto,
        es_predeterminada=True
    ).first()
    
    if not plantilla:
        messages.error(request, 'Este proyecto no tiene una plantilla configurada. Contacta al dueño del proyecto.')
        return redirect('articulos:ver_articulos', proyecto_id=proyecto_id)
    
    if request.method == 'POST':
        # Obtener todos los campos del formulario
        titulo = request.POST.get('titulo', '').strip()
        autores = request.POST.get('autores', '').strip()
        abstract = request.POST.get('abstract', '').strip()
        doi = request.POST.get('doi', '').strip()
        anio = request.POST.get('anio', '').strip()
        journal = request.POST.get('journal', '').strip()
        volumen = request.POST.get('volumen', '').strip()
        paginas = request.POST.get('paginas', '').strip()
        editorial = request.POST.get('editorial', '').strip()
        palabras_clave = request.POST.get('palabras_clave', '').strip()
        url = request.POST.get('url', '').strip()
        
        # 🆕 Obtener archivo PDF
        archivo_pdf = request.FILES.get('archivo_pdf', None)

        if not titulo:
            messages.error(request, 'El título es obligatorio.')
            return render(request, 'indv_articulo.html', {
                'proyecto': proyecto,
                'plantilla': plantilla
            })
        
        # 🆕 Validar archivo PDF si se proporcionó
        if archivo_pdf:
            # Validar tipo de archivo
            if not archivo_pdf.name.lower().endswith('.pdf'):
                messages.error(request, 'Solo se permiten archivos PDF.')
                return render(request, 'indv_articulo.html', {
                    'proyecto': proyecto,
                    'plantilla': plantilla
                })
            
            # Validar tamaño (50 MB máximo)
            max_size = 50 * 1024 * 1024  # 50 MB
            if archivo_pdf.size > max_size:
                messages.error(request, f'El archivo PDF no debe superar 50 MB. Tu archivo: {archivo_pdf.size / 1024 / 1024:.2f} MB')
                return render(request, 'indv_articulo.html', {
                    'proyecto': proyecto,
                    'plantilla': plantilla
                })

        # 🆕 Crear metadata_completos como dict
        metadata_completos = {
            'title': titulo,
        }
        if autores:
            metadata_completos['author'] = autores
        if abstract:
            metadata_completos['abstract'] = abstract
        if doi:
            metadata_completos['doi'] = doi
        if anio:
            metadata_completos['year'] = anio
        if journal:
            metadata_completos['journal'] = journal
        if volumen:
            metadata_completos['volume'] = volumen
        if paginas:
            metadata_completos['pages'] = paginas
        if editorial:
            metadata_completos['publisher'] = editorial
        if palabras_clave:
            metadata_completos['keywords'] = palabras_clave
        if url:
            metadata_completos['url'] = url

        # Generar bibtex_key único
        from django.utils.text import slugify
        primer_autor = autores.split(';')[0].split(',')[0].strip() if autores else 'anon'
        bibtex_key = f"{slugify(primer_autor)}_{anio}_{slugify(titulo[:20])}" if anio else f"{slugify(primer_autor)}_{slugify(titulo[:20])}"

        # 🆕 Construir bibtex_original válido (opcional pero recomendado)
        bibtex_lines = [f"@article{{{bibtex_key},"]
        for key, value in metadata_completos.items():
            if key != 'title':  # title ya está
                bibtex_lines.append(f'  {key} = {{{value}}},')
        bibtex_lines.append("}")
        bibtex_original = "\n".join(bibtex_lines)

        with transaction.atomic():
            # 🆕 Guardar con metadata_completos y bibtex_original
            articulo = Articulo.objects.create(
                proyecto=proyecto,
                usuario_carga=request.user,
                titulo=titulo,
                bibtex_key=bibtex_key,
                bibtex_original=bibtex_original,
                metadata_completos=metadata_completos,  # ✅ ¡ESTO ES CLAVE!
                archivo_bib=None,
                archivo_pdf=archivo_pdf,  # 🆕 Guardar archivo PDF si se proporcionó
                estado='PENDIENTE'
            )
            
            # 🆕 APLICAR PLANTILLA AUTOMÁTICAMENTE
            campos_asignados = aplicar_plantilla_proyecto_a_articulo(articulo, request.user)
            
            # 🔔 NOTIFICAR AL DUEÑO
            try:
                dueno = UsuarioProyecto.objects.get(
                    proyecto=proyecto,
                    rol_proyecto='DUEÑO'
                ).usuario
                
                if dueno != request.user:
                    mensaje_pdf = " (con PDF)" if archivo_pdf else ""
                    crear_notificacion_articulos(
                        usuario=dueno,
                        tipo='general',
                        titulo=f'Nuevo artículo agregado - {proyecto.nombre}',
                        mensaje=f'{request.user.get_full_name() or request.user.username} agregó "{titulo[:50]}"{mensaje_pdf} con {campos_asignados} tareas asignadas.',
                        url=reverse('articulos:ver_articulos', args=[proyecto.id]),
                        proyecto=proyecto
                    )
            except UsuarioProyecto.DoesNotExist:
                pass
            
            pdf_info = " con PDF agregado" if archivo_pdf else ""
            messages.success(request, f'✅ Artículo agregado{pdf_info} con {campos_asignados} tareas asignadas automáticamente.')
            return redirect('articulos:ver_articulos', proyecto_id=proyecto.id)
    
    return render(request, 'indv_articulo.html', {
        'proyecto': proyecto,
        'plantilla': plantilla  
    })



@login_required
def eliminar_articulo(request, articulo_id):
    """Vista para eliminar un artículo."""
    if request.method != 'POST':
        messages.error(request, 'Método no permitido.')
        return redirect('mis_proyectos')
    
    articulo = get_object_or_404(Articulo, id=articulo_id)
    proyecto_id = articulo.proyecto.id
    proyecto = articulo.proyecto

    # Verificar acceso
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto
    ).first()
    
    if not usuario_proyecto:
        messages.error(request, 'No tienes permiso para eliminar este artículo.')
        return redirect('mis_proyectos')

    # Guardar información antes de eliminar
    titulo_articulo = articulo.titulo
    bibtex_key = articulo.bibtex_key
    usuario_asignado = articulo.usuario_asignado

    # Registrar en historial antes de eliminar
    HistorialArticulo.objects.create(
        articulo=articulo,
        usuario=request.user,
        tipo_cambio='ELIMINACION',
        valor_anterior=titulo_articulo,
        valor_nuevo=f'Artículo eliminado por {request.user.get_full_name() or request.user.username}'
    )

    # 🔔 NOTIFICAR al usuario asignado (si existe y no es quien elimina)
    if usuario_asignado and usuario_asignado != request.user:
        crear_notificacion_articulos(
            usuario=usuario_asignado,
            tipo='general',
            titulo=f'Artículo eliminado - {proyecto.nombre}',
            mensaje=f'El artículo "{titulo_articulo[:50]}" que tenías asignado fue eliminado del proyecto.',
            url=reverse('articulos:ver_articulos', args=[proyecto_id]),
            proyecto=proyecto
        )

    # Eliminar el artículo
    articulo.delete()

    messages.success(request, f'Artículo "{titulo_articulo}" eliminado correctamente.')
    return redirect('articulos:ver_articulos', proyecto_id=proyecto_id)


# ==================== SUBIR ARCHIVOS .BIB ====================
# ==================== MAPEO DE VARIANTES DE CAMPOS BIBLIOGRÁFICOS ====================
CAMPO_MAPPING = {
    # === Título ===
    'title': 'title',
    'TITLE': 'title',
    'Title': 'title',
    'título': 'title',
    'TÍTULO': 'title',
    'Título': 'title',

    # === Autores ===
    'author': 'author',
    'AUTHOR': 'author',
    'Author': 'author',
    'authors': 'author',
    'AUTORS': 'author',  # (corrige si es typo)
    'Authors': 'author',
    'autor': 'author',
    'AUTOR': 'author',
    'Autor': 'author',
    'autores': 'author',
    'AUTORES': 'author',
    'Autores': 'author',

    # === Abstract / Resumen ===
    'abstract': 'abstract',
    'ABSTRACT': 'abstract',
    'Abstract': 'abstract',
    'resumen': 'abstract',
    'RESUMEN': 'abstract',
    'Resumen': 'abstract',
    'summary': 'abstract',
    'SUMMARY': 'abstract',
    'Summary': 'abstract',
    'annotation': 'abstract',
    'ANNOTATION': 'abstract',
    'Annotation': 'abstract',

    # === Año ===
    'year': 'year',
    'YEAR': 'year',
    'Year': 'year',
    'date': 'year',
    'DATE': 'year',
    'Date': 'year',
    'año': 'year',
    'AÑO': 'year',
    'Año': 'year',

    # === Revista ===
    'journal': 'journal',
    'JOURNAL': 'journal',
    'Journal': 'journal',
    'revista': 'journal',
    'REVISTA': 'journal',
    'Revista': 'journal',
    'booktitle': 'journal',

    # === Volumen ===
    'volume': 'volume',
    'VOLUME': 'volume',
    'Volume': 'volume',
    'volumen': 'volume',
    'VOLUMEN': 'volume',
    'Volumen': 'volume',
    'vol': 'volume',

    # === Número ===
    'number': 'number',
    'NUMBER': 'number',
    'Number': 'number',
    'issue': 'number',
    'ISSUE': 'number',
    'Issue': 'number',
    'número': 'number',
    'NÚMERO': 'number',
    'Número': 'number',

    # === Páginas ===
    'pages': 'pages',
    'PAGES': 'pages',
    'Pages': 'pages',
    'pagina': 'pages',
    'PAGINA': 'pages',
    'Página': 'pages',
    'paginas': 'pages',
    'PAGINAS': 'pages',
    'Páginas': 'pages',
    'page': 'pages',

    # === DOI ===
    'doi': 'doi',
    'DOI': 'doi',
    'Doi': 'doi',

    # === URL ===
    'url': 'url',
    'URL': 'url',
    'Url': 'url',
    'link': 'url',

    # === Keywords ===
    'keywords': 'keywords',
    'KEYWORDS': 'keywords',
    'Keywords': 'keywords',
    'keyword': 'keywords',
    'palabrasclave': 'keywords',
    'PALABRASCLAVE': 'keywords',
    'Palabrasclave': 'keywords',
    'palabras_clave': 'keywords',
    'Palabras clave': 'keywords',
}

def normalizar_campos(entry):
    """Normaliza nombres de campos bibliográficos a un estándar interno."""
    normalized = {}
    for key, value in entry.items():
        std_key = CAMPO_MAPPING.get(key, key)  # Si no está en el mapeo, mantener original
        if std_key in normalized:
            # Si ya existe, concatenar (poco común, pero seguro)
            if isinstance(normalized[std_key], list):
                normalized[std_key].append(value)
            else:
                normalized[std_key] = [normalized[std_key], value]
        else:
            normalized[std_key] = value
    return normalized

@login_required
def subir_archivo(request, proyecto_id):
    """
    🆕 MODIFICADA: Aplica automáticamente la plantilla del proyecto a cada artículo subido
    """
    try:
        proyecto = Proyecto.objects.get(id=proyecto_id)
    except (Proyecto.DoesNotExist, ValueError):
        messages.error(request, "El proyecto no existe.")
        return redirect('mis_proyectos')
    
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto
    ).first()
    
    if not usuario_proyecto:
        messages.error(request, 'No tienes acceso a este proyecto.')
        return redirect('mis_proyectos')
    
    request.session['proyecto_actual_id'] = proyecto.id
    
    if 'archivos_sesion' not in request.session or request.session['archivos_sesion'] is None:
        request.session['archivos_sesion'] = []
        request.session.modified = True
    
    # 🆕 VERIFICAR SI EL PROYECTO TIENE PLANTILLA (OBLIGATORIO)
    plantilla = PlantillaBusqueda.objects.filter(
        proyecto=proyecto,
        es_predeterminada=True
    ).first()
    
    if not plantilla:
        messages.error(request, 'Este proyecto no tiene una plantilla configurada. Contacta al dueño del proyecto.')
        return redirect('articulos:ver_articulos', proyecto_id=proyecto_id)
    
    if request.method == 'POST':
        archivo = request.FILES.get('archivo')

        if not archivo:
            messages.error(request, "Debes seleccionar un archivo .bib")
        elif not archivo.name.endswith('.bib'):
            messages.error(request, "Solo se permiten archivos con extensión .bib")
        else:
            nuevo_archivo = ArchivoSubida.objects.create(
                proyecto=proyecto,
                usuario=request.user,
                nombre_archivo=archivo.name,
            )

            cantidad_articulos_procesados = 0
            cantidad_campos_asignados_total = 0  # 🆕 Contador total
            errores = []

            try:
                parser = BibTexParser(common_strings=True)
                parser.ignore_nonstandard_types = False
                parser.homogenize_fields = True
                
                contenido = None
                for encoding in ['utf-8', 'latin-1', 'iso-8859-1']:
                    try:
                        contenido = archivo.read().decode(encoding)
                        archivo.seek(0)
                        break
                    except (UnicodeDecodeError, AttributeError):
                        continue
                
                if not contenido:
                    raise Exception("No se pudo leer el archivo con ningún encoding soportado")
                
                bib_database = bibtexparser.loads(contenido, parser=parser)
                
                if not bib_database.entries:
                    errores.append({'error': 'No se encontraron entradas válidas en el archivo .bib'})
                
                # 🆕 NORMALIZAR CAMPOS
                from .views import normalizar_campos  # Importar la función existente
                
                for entry in bib_database.entries:
                    try:
                        bibtex_key = entry.get('ID', '')
                        
                        if not bibtex_key:
                            errores.append({
                                'entry': 'Sin ID',
                                'error': 'La entrada no tiene un ID válido'
                            })
                            continue
                        
                        if Articulo.objects.filter(
                            bibtex_key=bibtex_key,
                            proyecto=proyecto
                        ).exists():
                            errores.append({
                                'entry': bibtex_key,
                                'error': 'Ya existe un artículo con esta clave en este proyecto'
                            })
                            continue
                        
                        # Crear string BibTeX
                        entry_type = entry.get('ENTRYTYPE', 'article').upper()
                        bibtex_str = f"@{entry_type}{{{bibtex_key},\n"
                        
                        for key, value in entry.items():
                            if key not in ['ENTRYTYPE', 'ID']:
                                value_clean = str(value).strip()
                                bibtex_str += f"  {key} = {{{value_clean}}},\n"
                        bibtex_str += "}"
                        
                        # Normalizar campos
                        entry_normalizado = normalizar_campos(entry)
                        
                        # Extraer título
                        titulo = entry_normalizado.get('title', 'Sin título')
                        if isinstance(titulo, str):
                            titulo = titulo.strip()
                        elif isinstance(titulo, list):
                            titulo = titulo[0].strip() if titulo else 'Sin título'
                        
                        # 🆕 CREAR ARTÍCULO CON TRANSACCIÓN
                        with transaction.atomic():
                            articulo = Articulo.objects.create(
                                proyecto=proyecto,
                                usuario_carga=request.user,
                                bibtex_key=bibtex_key,
                                titulo=titulo[:500],
                                doi=entry_normalizado.get('doi', None),
                                bibtex_original=bibtex_str,
                                metadata_completos=entry_normalizado,
                                archivo_bib=archivo.name,
                                estado='PENDIENTE'  # 🆕 Ya viene con tareas asignadas
                            )
                            
                            # 🆕 APLICAR PLANTILLA AUTOMÁTICAMENTE
                            campos_asignados = aplicar_plantilla_proyecto_a_articulo(articulo, request.user)
                            cantidad_campos_asignados_total += campos_asignados
                            
                            cantidad_articulos_procesados += 1
                        
                    except Exception as e:
                        error_msg = str(e)
                        errores.append({
                            'entry': entry.get('ID', 'desconocido'),
                            'error': error_msg
                        })
                        
            except Exception as e:
                error_msg = str(e)
                errores.append({'error': f'Error al procesar archivo: {error_msg}'})

            # Guardar resultados
            nuevo_archivo.articulos_procesados = cantidad_articulos_procesados
            if errores:
                nuevo_archivo.errores_procesamiento = errores
            nuevo_archivo.save()
            
            # Agregar a sesión
            archivos_sesion = request.session.get('archivos_sesion', [])
            archivos_sesion.append(nuevo_archivo.id)
            request.session['archivos_sesion'] = archivos_sesion
            request.session.modified = True
            
            # 🔔 NOTIFICAR AL DUEÑO
            if cantidad_articulos_procesados > 0:
                try:
                    dueno = UsuarioProyecto.objects.get(
                        proyecto=proyecto,
                        rol_proyecto='DUEÑO'
                    ).usuario
                    
                    if dueno != request.user:
                        crear_notificacion_articulos(
                            usuario=dueno,
                            tipo='general',
                            titulo=f'Archivo .bib subido - {proyecto.nombre}',
                            mensaje=f'{request.user.get_full_name() or request.user.username} subió "{archivo.name}" con {cantidad_articulos_procesados} artículos ({cantidad_campos_asignados_total} tareas asignadas automáticamente).',
                            url=reverse('articulos:ver_articulos', args=[proyecto.id]),
                            proyecto=proyecto
                        )
                except UsuarioProyecto.DoesNotExist:
                    pass
            
            # Mensajes al usuario
            if cantidad_articulos_procesados > 0:
                messages.success(
                    request, 
                    f"✅ {cantidad_articulos_procesados} artículo(s) procesados con {cantidad_campos_asignados_total} tarea(s) asignadas automáticamente"
                )
            else:
                messages.warning(request, "⚠️ No se procesaron artículos. Revisa el formato del archivo.")
            
            if errores:
                messages.warning(request, f"Se encontraron {len(errores)} errores durante el procesamiento.")
            
            return redirect('articulos:subir_archivo', proyecto_id=proyecto_id)

    # GET: Mostrar formulario
    archivos_ids = request.session.get('archivos_sesion', [])
    archivos = ArchivoSubida.objects.filter(id__in=archivos_ids).order_by('-fecha_subida')
    
    return render(request, 'subir.html', {
        'proyecto_id': proyecto_id,
        'proyecto': proyecto,
        'archivos': archivos,
        'plantilla': plantilla 
    })


# ==================== GESTIÓN DE CAMPOS DE METAANÁLISIS ====================

@login_required
def gestionar_campos(request, proyecto_id):
    """
    🆕 MODIFICADA: Ahora redirige a la nueva vista de editar plantilla
    """
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto,
        rol_proyecto='DUEÑO'
    ).first()
    
    if not usuario_proyecto:
        messages.error(request, 'Solo el Dueño del proyecto puede gestionar campos.')
        return redirect('detalle_proyecto', proyecto_id=proyecto_id)

    messages.info(request, 'Ahora los campos se gestionan desde la plantilla del proyecto.')
    return redirect('articulos:editar_plantilla_proyecto', proyecto_id=proyecto_id)


@login_required
def eliminar_campo(request, campo_id):
    """
    🆕 MODIFICADA: Valida si el campo está en uso en la plantilla del proyecto antes de eliminar
    """
    campo = get_object_or_404(CampoMetanalisis, id=campo_id)
    proyecto_id = campo.proyecto.id if campo.proyecto else None
    
    if campo.es_predefinido:
        messages.error(request, 'No se pueden eliminar campos predefinidos del sistema.')
    elif campo.proyecto:
        # 🆕 VALIDAR SI ESTÁ EN LA PLANTILLA DEL PROYECTO
        en_plantilla = PlantillaBusqueda.objects.filter(
            proyecto=campo.proyecto,
            campos=campo
        ).exists()
        
        if en_plantilla:
            messages.error(request, f'No puedes eliminar "{campo.nombre}" porque está en la plantilla del proyecto. Primero quítalo de la plantilla.')
        elif campo.asignaciones.exists():
            messages.error(request, f'No puedes eliminar "{campo.nombre}" porque ya está asignado a artículos.')
        else:
            nombre = campo.nombre
            campo.delete()
            messages.success(request, f'✅ Campo "{nombre}" eliminado exitosamente.')
    else:
        messages.error(request, 'No tienes permiso para eliminar este campo.')
    
    if proyecto_id:
        return redirect('articulos:editar_plantilla_proyecto', proyecto_id=proyecto_id)
    return redirect('articulos:ver_articulos')

# ==================== WORKSPACE Y SISTEMA DE REVISIÓN ====================

@login_required
def workspace_articulo(request, articulo_id):
    """
    Workspace principal para trabajar en un artículo.
    Roles:
    - COLABORADOR: Solo sus artículos asignados, envía a revisión
    - SUPERVISOR/DUEÑO: Todos los artículos, puede aprobar directamente
    
    🆕 Mejoras:
    - Separa campos bloqueados (aprobados) de editables
    - Detecta si el artículo fue reactivado después de aprobación
    - Permite trabajar en artículos APROBADOS con nuevos campos
    """
    articulo = get_object_or_404(Articulo, id=articulo_id)
    proyecto = articulo.proyecto
    
    # Verificar acceso al proyecto
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto
    ).first()
    
    if not usuario_proyecto:
        messages.error(request, 'No tienes acceso a este proyecto.')
        return redirect('mis_proyectos')
    
    # Control de acceso por rol
    es_supervisor_o_dueno = usuario_proyecto.rol_proyecto in ['SUPERVISOR', 'DUEÑO']
    
    # COLABORADOR: Solo puede ver artículos que le pertenecen
    if usuario_proyecto.rol_proyecto == 'COLABORADOR':
        if articulo.usuario_asignado != request.user and articulo.usuario_carga != request.user:
            messages.error(request, 'No tienes permiso para acceder a este artículo.')
            return redirect('articulos:ver_articulos', proyecto_id=proyecto.id)
    
    # 🆕 PERMITIR acceso a artículos EN_ESPERA pero mostrar mensaje
    if articulo.estado == 'EN_ESPERA':
        messages.warning(request, 'Este artículo aún no tiene tareas asignadas.')
        return redirect('articulos:ver_articulos', proyecto_id=proyecto.id)
    
    # Obtener campos asignados con prefetch
    campos_asignados = AsignacionCampo.objects.filter(
        articulo=articulo
    ).select_related('campo', 'asignado_por').order_by('campo__categoria', 'campo__nombre')
    
    # 🆕 SEPARAR campos aprobados (bloqueados) de pendientes/editables
    campos_bloqueados = campos_asignados.filter(aprobado=True).order_by('campo__categoria', 'campo__nombre')
    campos_editables = campos_asignados.filter(aprobado=False).order_by('campo__categoria', 'campo__nombre')
    
    # Obtener historial de cambios
    historial = HistorialArticulo.objects.filter(
        articulo=articulo
    ).select_related('usuario').order_by('-fecha_cambio')[:20]
    
    # Obtener comentarios de revisión
    comentarios = ComentarioRevision.objects.filter(
        articulo=articulo
    ).select_related('supervisor', 'colaborador').order_by('-fecha_comentario')
    
    # Calcular progreso
    total_campos = campos_asignados.count()
    campos_completados = campos_asignados.filter(completado=True).count()
    campos_aprobados = campos_asignados.filter(aprobado=True).count()
    progreso_porcentaje = (campos_completados / total_campos * 100) if total_campos > 0 else 0
    progreso_aprobacion = (campos_aprobados / campos_completados * 100) if campos_completados > 0 else 0
    
    # 🆕 Detectar si es un artículo reactivado (tiene campos aprobados pero está en PENDIENTE/EN_PROCESO)
    articulo_reactivado = (
        articulo.estado in ['PENDIENTE', 'EN_PROCESO'] and 
        campos_bloqueados.exists()
    )
    
    # 🆕 Estadísticas adicionales para campos bloqueados vs editables
    total_campos_bloqueados = campos_bloqueados.count()
    total_campos_editables = campos_editables.count()
    campos_editables_completados = campos_editables.filter(completado=True).count()
    progreso_editables = (campos_editables_completados / total_campos_editables * 100) if total_campos_editables > 0 else 0
    
    # 🆕 Agrupar campos bloqueados por categoría
    from itertools import groupby
    from operator import attrgetter
    
    campos_bloqueados_agrupados = []
    for categoria, items in groupby(campos_bloqueados, key=lambda x: x.campo.get_categoria_display()):
        campos_bloqueados_agrupados.append({
            'categoria': categoria,
            'campos': list(items)
        })
    
    # 🆕 Agrupar campos editables por categoría
    campos_editables_agrupados = []
    for categoria, items in groupby(campos_editables, key=lambda x: x.campo.get_categoria_display()):
        campos_editables_agrupados.append({
            'categoria': categoria,
            'campos': list(items)
        })
    
    # 🆕 Mensaje informativo para colaboradores en artículos reactivados
    mensaje_reactivacion = None
    if articulo_reactivado and not es_supervisor_o_dueno:
        mensaje_reactivacion = (
            f"Este artículo fue aprobado anteriormente con {total_campos_bloqueados} campo(s) ya completado(s). "
            f"Se han agregado {total_campos_editables} nuevo(s) campo(s) que debes completar. "
            f"Los campos ya aprobados permanecen bloqueados y visibles solo como referencia."
        )
    elif articulo_reactivado and es_supervisor_o_dueno:
        mensaje_reactivacion = (
            f"Este artículo tiene {total_campos_bloqueados} campo(s) ya aprobado(s). "
            f"Se agregaron {total_campos_editables} campo(s) nuevo(s) que el colaborador debe completar."
        )
    
    context = {
        'articulo': articulo,
        'proyecto': proyecto,
        'usuario_proyecto': usuario_proyecto,
        'es_supervisor_o_dueno': es_supervisor_o_dueno,
        
        # 🔹 CAMPOS COMPLETOS (para compatibilidad con templates existentes)
        'campos_asignados': campos_asignados,
        
        # 🆕 CAMPOS SEPARADOS por estado
        'campos_bloqueados': campos_bloqueados,
        'campos_editables': campos_editables,
        'campos_bloqueados_agrupados': campos_bloqueados_agrupados,
        'campos_editables_agrupados': campos_editables_agrupados,
        
        # Historial y comentarios
        'historial': historial,
        'comentarios': comentarios,
        
        # 🔹 ESTADÍSTICAS GENERALES
        'total_campos': total_campos,
        'campos_completados': campos_completados,
        'campos_aprobados': campos_aprobados,
        'progreso_porcentaje': round(progreso_porcentaje, 1),
        'progreso_aprobacion': round(progreso_aprobacion, 1),
        
        # 🆕 ESTADÍSTICAS POR TIPO DE CAMPO
        'total_campos_bloqueados': total_campos_bloqueados,
        'total_campos_editables': total_campos_editables,
        'campos_editables_completados': campos_editables_completados,
        'progreso_editables': round(progreso_editables, 1),
        
        # 🔹 PERMISOS
        'puede_editar': articulo.estado not in ['APROBADO'],
        'puede_aprobar': es_supervisor_o_dueno,
        'puede_enviar_revision': articulo.estado in ['PENDIENTE', 'EN_PROCESO'],
        
        # 🆕 INDICADORES DE ESTADO ESPECIAL
        'articulo_reactivado': articulo_reactivado,
        'mensaje_reactivacion': mensaje_reactivacion,
        
        # 🆕 INDICADOR: ¿Puede completarse con solo campos editables?
        'puede_completar_solo_editables': (
            total_campos_editables > 0 and 
            campos_editables_completados == total_campos_editables
        ),
        
        # 🆕 INDICADOR: Mostrar sección de campos bloqueados
        'mostrar_campos_bloqueados': campos_bloqueados.exists(),
    }
    
    # 🆕 SELECCIONAR TEMPLATE
    # Usar un único template que se adapta basado en si hay PDF o no
    template_name = 'workspace.html'
    
    return render(request, template_name, context)

# ==================== GUARDAR CAMPO (AJAX) ====================

@login_required
def guardar_campo_workspace(request, articulo_id):
    """
    Guarda el valor de un campo específico del artículo.
    Cambia automáticamente el estado a EN_PROCESO si estaba PENDIENTE.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)
    
    articulo = get_object_or_404(Articulo, id=articulo_id)
    
    # Verificar acceso
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=articulo.proyecto
    ).first()
    
    if not usuario_proyecto:
        return JsonResponse({'success': False, 'error': 'No tienes acceso'}, status=403)
    
    # Verificar que puede editar
    if articulo.estado == 'APROBADO':
        return JsonResponse({'success': False, 'error': 'Este artículo ya fue aprobado'}, status=400)
    
    try:
        data = json.loads(request.body)
        campo_id = data.get('campo_id')
        valor = data.get('valor', '').strip()
        
        # Obtener asignación
        asignacion = get_object_or_404(
            AsignacionCampo,
            articulo=articulo,
            campo_id=campo_id
        )
        
        # 🆕 Verificar si el campo está aprobado
        if asignacion.aprobado:
            return JsonResponse({
                'success': False,
                'error': 'Este campo ya fue aprobado y no puede ser modificado'
            }, status=400)
        
        # Usar el método del modelo para guardar
        asignacion.marcar_completado(valor, usuario=request.user)
        
        # Cambiar estado a EN_PROCESO si estaba PENDIENTE
        if articulo.estado == 'PENDIENTE' and valor:
            articulo.cambiar_estado('EN_PROCESO', usuario=request.user)
            estado_cambiado = True
        else:
            estado_cambiado = False
        
        # Calcular nuevo progreso
        total_campos = articulo.campos_asignados.count()
        campos_completados = articulo.campos_asignados.filter(completado=True).count()
        progreso = (campos_completados / total_campos * 100) if total_campos > 0 else 0
        
        return JsonResponse({
            'success': True,
            'mensaje': 'Campo guardado exitosamente',
            'estado_cambiado': estado_cambiado,
            'nuevo_estado': articulo.get_estado_display(),
            'campos_completados': campos_completados,
            'total_campos': total_campos,
            'progreso_porcentaje': round(progreso, 1)
        })
    
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Datos inválidos'}, status=400)
    except Exception as e:
        print(f"❌ Error en guardar_campo_workspace: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==================== APROBACIÓN DE CAMPOS INDIVIDUALES ====================

@login_required
def aprobar_campo_individual(request, asignacion_id):
    """
    Aprueba un campo individual dentro del workspace
    Solo SUPERVISORES y DUEÑOS
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)
    
    asignacion = get_object_or_404(AsignacionCampo, id=asignacion_id)
    articulo = asignacion.articulo
    proyecto = articulo.proyecto
    
    # Verificar rol
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto,
        rol_proyecto__in=['SUPERVISOR', 'DUEÑO']
    ).first()
    
    if not usuario_proyecto:
        return JsonResponse({'success': False, 'error': 'No tienes permisos'}, status=403)
    
    # Validar que el campo esté completado
    if not asignacion.completado or not asignacion.valor:
        return JsonResponse({
            'success': False,
            'error': 'Solo puedes aprobar campos que hayan sido completados'
        }, status=400)
    
    try:
        # Aprobar el campo
        asignacion.aprobar_campo(supervisor=request.user)
        
        # Calcular progreso de aprobación
        total_completados = articulo.campos_asignados.filter(completado=True).count()
        total_aprobados = articulo.campos_asignados.filter(aprobado=True).count()
        progreso_aprobacion = round((total_aprobados / total_completados * 100), 1) if total_completados > 0 else 0
        
        # Si todos los campos completados están aprobados, cambiar estado del artículo
        if articulo.puede_aprobar_articulo() and articulo.estado == 'EN_REVISION':
            articulo.cambiar_estado('APROBADO', usuario=request.user)
            articulo_aprobado_completo = True
            
            # 🔔 Notificar al colaborador
            colaborador = articulo.usuario_asignado or articulo.usuario_carga
            if colaborador and colaborador.id != request.user.id:
                crear_notificacion_articulos(
                    usuario=colaborador,
                    tipo='tarea_aprobada',
                    titulo=f'✅ Artículo completamente aprobado - {proyecto.nombre}',
                    mensaje=f'Todos los campos del artículo "{articulo.titulo[:50]}..." han sido aprobados. ¡Excelente trabajo!',
                    url=reverse('articulos:workspace_articulo', args=[articulo.id]),
                    proyecto=proyecto
                )
        else:
            articulo_aprobado_completo = False
        
        return JsonResponse({
            'success': True,
            'mensaje': f'Campo "{asignacion.campo.nombre}" aprobado',
            'campo_aprobado': True,
            'progreso_aprobacion': progreso_aprobacion,
            'total_aprobados': total_aprobados,
            'total_completados': total_completados,
            'articulo_aprobado_completo': articulo_aprobado_completo,
            'nuevo_estado_articulo': articulo.get_estado_display() if articulo_aprobado_completo else None
        })
    
    except Exception as e:
        print(f"❌ Error en aprobar_campo_individual: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def solicitar_correccion_campo(request, asignacion_id):
    """
    Solicita corrección en un campo específico
    Quita la aprobación si ya estaba aprobado
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)
    
    asignacion = get_object_or_404(AsignacionCampo, id=asignacion_id)
    articulo = asignacion.articulo
    proyecto = articulo.proyecto
    
    # Verificar rol
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto,
        rol_proyecto__in=['SUPERVISOR', 'DUEÑO']
    ).first()
    
    if not usuario_proyecto:
        return JsonResponse({'success': False, 'error': 'No tienes permisos'}, status=403)
    
    try:
        data = json.loads(request.body)
        comentario = data.get('comentario', '').strip()
        
        if not comentario:
            return JsonResponse({
                'success': False,
                'error': 'Debes proporcionar un comentario'
            }, status=400)
        
        # Quitar aprobación si tenía
        if asignacion.aprobado:
            asignacion.desaprobar_campo(supervisor=request.user, razon=comentario)
        
        # Guardar comentario en el campo de notas
        nota_anterior = asignacion.notas or ""
        nueva_nota = f"[{timezone.now().strftime('%d/%m/%Y %H:%M')}] {request.user.get_full_name() or request.user.username}: {comentario}"
        asignacion.notas = f"{nota_anterior}\n{nueva_nota}" if nota_anterior else nueva_nota
        asignacion.save()
        
        # Crear comentario de revisión general
        colaborador = articulo.usuario_asignado or articulo.usuario_carga
        ComentarioRevision.objects.create(
            articulo=articulo,
            supervisor=request.user,
            colaborador=colaborador,
            comentario=f'Campo "{asignacion.campo.nombre}": {comentario}',
            tipo_accion='CORRECCION'
        )
        
        # Si el artículo estaba APROBADO, volver a EN_REVISION
        if articulo.estado == 'APROBADO':
            articulo.cambiar_estado('EN_REVISION', usuario=request.user)
        
        # 🔔 Notificar al colaborador
        if colaborador and colaborador.id != request.user.id:
            crear_notificacion_articulos(
                usuario=colaborador,
                tipo='tarea_correccion',
                titulo=f'🔄 Corrección solicitada en campo - {proyecto.nombre}',
                mensaje=f'Corrección en "{asignacion.campo.nombre}" del artículo "{articulo.titulo[:50]}...": {comentario[:100]}',
                url=reverse('articulos:workspace_articulo', args=[articulo.id]),
                proyecto=proyecto
            )
        
        return JsonResponse({
            'success': True,
            'mensaje': 'Corrección solicitada exitosamente',
            'campo_desaprobado': True,
            'comentario_agregado': nueva_nota
        })
    
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Datos inválidos'}, status=400)
    except Exception as e:
        print(f"❌ Error en solicitar_correccion_campo: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==================== ENVIAR A REVISIÓN ====================

@login_required
def enviar_a_revision(request, articulo_id):
    """
    Envía un artículo a revisión (COLABORADOR)
    Notifica a SUPERVISORES y DUEÑO
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)
    
    articulo = get_object_or_404(Articulo, id=articulo_id)
    proyecto = articulo.proyecto
    
    # Verificar acceso
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto
    ).first()
    
    if not usuario_proyecto:
        return JsonResponse({'success': False, 'error': 'No tienes acceso'}, status=403)
    
    # Validar que puede enviar a revisión
    if articulo.estado not in ['PENDIENTE', 'EN_PROCESO']:
        return JsonResponse({
            'success': False,
            'error': f'No puedes enviar a revisión un artículo en estado {articulo.get_estado_display()}'
        }, status=400)
    
    try:
        # Cambiar estado
        articulo.cambiar_estado('EN_REVISION', usuario=request.user)
        
        # Registrar en historial
        HistorialArticulo.objects.create(
            articulo=articulo,
            usuario=request.user,
            tipo_cambio='ENVIO_REVISION',
            valor_nuevo='Enviado a revisión'
        )
        
        # 🔔 NOTIFICAR A SUPERVISORES Y DUEÑO
        revisores = UsuarioProyecto.objects.filter(
            proyecto=proyecto,
            rol_proyecto__in=['SUPERVISOR', 'DUEÑO']
        ).exclude(usuario=request.user)
        
        usuarios_notificados = 0
        for revisor in revisores:
            crear_notificacion_articulos(
                usuario=revisor.usuario,
                tipo='tarea_revision',
                titulo=f'📝 Artículo enviado a revisión - {proyecto.nombre}',
                mensaje=f'{request.user.get_full_name() or request.user.username} ha enviado el artículo "{articulo.titulo[:50]}..." para tu revisión.',
                url=reverse('articulos:workspace_articulo', args=[articulo.id]),
                proyecto=proyecto
            )
            usuarios_notificados += 1
        
        return JsonResponse({
            'success': True,
            'mensaje': 'Artículo enviado a revisión exitosamente',
            'usuarios_notificados': usuarios_notificados,
            'nuevo_estado': articulo.get_estado_display()
        })
    
    except Exception as e:
        print(f"❌ Error en enviar_a_revision: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def enviar_masivo_revision(request, proyecto_id):
    """
    Permite a un COLABORADOR enviar múltiples artículos a revisión
    de forma masiva usando checkboxes
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)
    
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    
    # Verificar acceso
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto
    ).first()
    
    if not usuario_proyecto:
        return JsonResponse({'success': False, 'error': 'No tienes acceso'}, status=403)
    
    try:
        data = json.loads(request.body)
        articulos_ids = data.get('articulos_ids', [])
        
        if not articulos_ids:
            return JsonResponse({
                'success': False,
                'error': 'Debes seleccionar al menos un artículo'
            })
        
        # Filtrar artículos que puede enviar
        articulos = Articulo.objects.filter(
            id__in=articulos_ids,
            proyecto=proyecto,
            estado__in=['PENDIENTE', 'EN_PROCESO']
        )
        
        # Si es COLABORADOR, solo sus artículos
        if usuario_proyecto.rol_proyecto == 'COLABORADOR':
            articulos = articulos.filter(
                Q(usuario_asignado=request.user) | Q(usuario_carga=request.user)
            )
        
        articulos_enviados = 0
        
        for articulo in articulos:
            # Cambiar estado
            articulo.cambiar_estado('EN_REVISION', usuario=request.user)
            
            # Registrar en historial
            HistorialArticulo.objects.create(
                articulo=articulo,
                usuario=request.user,
                tipo_cambio='ENVIO_REVISION',
                valor_nuevo='Enviado a revisión masivamente'
            )
            
            articulos_enviados += 1
        
        # 🔔 NOTIFICAR A SUPERVISORES (una sola notificación agrupada)
        if articulos_enviados > 0:
            revisores = UsuarioProyecto.objects.filter(
                proyecto=proyecto,
                rol_proyecto__in=['SUPERVISOR', 'DUEÑO']
            ).exclude(usuario=request.user)
            
            for revisor in revisores:
                if articulos_enviados == 1:
                    mensaje = f'{request.user.get_full_name() or request.user.username} ha enviado 1 artículo para tu revisión.'
                    titulo = f'📝 Artículo enviado a revisión - {proyecto.nombre}'
                else:
                    mensaje = f'{request.user.get_full_name() or request.user.username} ha enviado {articulos_enviados} artículos para tu revisión.'
                    titulo = f'📝 {articulos_enviados} artículos enviados a revisión - {proyecto.nombre}'
                
                crear_notificacion_articulos(
                    usuario=revisor.usuario,
                    tipo='tarea_revision',
                    titulo=titulo,
                    mensaje=mensaje,
                    url=reverse('articulos:bandeja_revision', args=[proyecto.id]),
                    proyecto=proyecto
                )
        
        return JsonResponse({
            'success': True,
            'mensaje': f'Se enviaron {articulos_enviados} artículo(s) a revisión exitosamente',
            'articulos_enviados': articulos_enviados
        })
    
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Datos inválidos'}, status=400)
    except Exception as e:
        print(f"❌ Error en enviar_masivo_revision: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==================== APROBAR ARTÍCULO ====================

@login_required
def aprobar_articulo(request, articulo_id):
    """
    Aprueba un artículo completo (SUPERVISOR/DUEÑO)
    🆕 Aprueba automáticamente todos los campos completados
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)
    
    articulo = get_object_or_404(Articulo, id=articulo_id)
    proyecto = articulo.proyecto
    
    # Verificar rol de supervisor/dueño
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto,
        rol_proyecto__in=['SUPERVISOR', 'DUEÑO']
    ).first()
    
    if not usuario_proyecto:
        return JsonResponse({
            'success': False,
            'error': 'Solo Supervisores y Dueños pueden aprobar artículos'
        }, status=403)
    
    try:
        data = json.loads(request.body)
        comentario_texto = data.get('comentario', '').strip()
        
        # Cambiar estado a APROBADO
        articulo.cambiar_estado('APROBADO', usuario=request.user)
        
        # 🆕 Aprobar todos los campos completados automáticamente
        campos_aprobados = 0
        for asignacion in articulo.campos_asignados.filter(completado=True, aprobado=False):
            asignacion.aprobar_campo(supervisor=request.user)
            campos_aprobados += 1
        
        # Registrar en historial
        mensaje_historial = f'Aprobado por {request.user.get_full_name() or request.user.username}'
        if campos_aprobados > 0:
            mensaje_historial += f' ({campos_aprobados} campos aprobados automáticamente)'
        
        HistorialArticulo.objects.create(
            articulo=articulo,
            usuario=request.user,
            tipo_cambio='APROBACION',
            valor_nuevo=mensaje_historial
        )
        
        # Si hay comentario, guardarlo
        if comentario_texto:
            ComentarioRevision.objects.create(
                articulo=articulo,
                supervisor=request.user,
                colaborador=articulo.usuario_asignado or articulo.usuario_carga,
                comentario=comentario_texto,
                tipo_accion='APROBADO'
            )
        
        # 🔔 NOTIFICAR AL COLABORADOR (si no es quien aprobó)
        usuario_responsable = articulo.usuario_asignado or articulo.usuario_carga
        if usuario_responsable and usuario_responsable.id != request.user.id:
            mensaje_notif = f'¡Felicidades! Tu artículo "{articulo.titulo[:50]}..." ha sido aprobado por {request.user.get_full_name() or request.user.username}.'
            if comentario_texto:
                mensaje_notif += f' Comentario: "{comentario_texto[:100]}"'
            
            crear_notificacion_articulos(
                usuario=usuario_responsable,
                tipo='tarea_aprobada',
                titulo=f'✅ Artículo aprobado - {proyecto.nombre}',
                mensaje=mensaje_notif,
                url=reverse('articulos:workspace_articulo', args=[articulo.id]),
                proyecto=proyecto
            )
        
        return JsonResponse({
            'success': True,
            'mensaje': 'Artículo aprobado exitosamente',
            'campos_aprobados': campos_aprobados,
            'redirect_url': reverse('articulos:bandeja_revision', args=[proyecto.id])
        })
    
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Datos inválidos'}, status=400)
    except Exception as e:
        print(f"❌ Error en aprobar_articulo: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==================== SOLICITAR CORRECCIÓN ====================

@login_required
def solicitar_correccion(request, articulo_id):
    """
    Devuelve un artículo al colaborador con comentarios de corrección
    El artículo pasa de EN_REVISION a PENDIENTE
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)
    
    articulo = get_object_or_404(Articulo, id=articulo_id)
    proyecto = articulo.proyecto
    
    # Verificar rol
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto,
        rol_proyecto__in=['SUPERVISOR', 'DUEÑO']
    ).first()
    
    if not usuario_proyecto:
        return JsonResponse({'success': False, 'error': 'No tienes permisos'}, status=403)
    
    # Validar estado
    if articulo.estado != 'EN_REVISION':
        return JsonResponse({
            'success': False,
            'error': 'Solo puedes solicitar corrección a artículos en revisión'
        }, status=400)
    
    try:
        data = json.loads(request.body)
        comentario_texto = data.get('comentario', '').strip()
        
        if not comentario_texto:
            return JsonResponse({
                'success': False,
                'error': 'Debes proporcionar un comentario de retroalimentación'
            }, status=400)
        
        # Cambiar estado a PENDIENTE (mantiene los cambios guardados)
        articulo.cambiar_estado('PENDIENTE', usuario=request.user)
        
        # Registrar en historial
        HistorialArticulo.objects.create(
            articulo=articulo,
            usuario=request.user,
            tipo_cambio='SOLICITUD_CORRECCION',
            valor_nuevo=f'Requiere corrección: {comentario_texto[:100]}'
        )
        
        # Guardar comentario
        colaborador = articulo.usuario_asignado or articulo.usuario_carga
        ComentarioRevision.objects.create(
            articulo=articulo,
            supervisor=request.user,
            colaborador=colaborador,
            comentario=comentario_texto,
            tipo_accion='CORRECCION'
        )
        
        # 🔔 NOTIFICAR AL COLABORADOR
        if colaborador:
            crear_notificacion_articulos(
                usuario=colaborador,
                tipo='tarea_correccion',
                titulo=f'🔄 Corrección solicitada - {proyecto.nombre}',
                mensaje=f'{request.user.get_full_name() or request.user.username} solicita correcciones en tu artículo "{articulo.titulo[:50]}...". Comentario: "{comentario_texto[:100]}"',
                url=reverse('articulos:workspace_articulo', args=[articulo.id]),
                proyecto=proyecto
            )
        
        return JsonResponse({
            'success': True,
            'mensaje': 'Corrección solicitada exitosamente',
            'redirect_url': reverse('articulos:bandeja_revision', args=[proyecto.id])
        })
    
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Datos inválidos'}, status=400)
    except Exception as e:
        print(f"❌ Error en solicitar_correccion: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==================== BANDEJA DE REVISIÓN ====================

@login_required
def bandeja_revision(request, proyecto_id):
    """
    Vista de SUPERVISORES/DUEÑOS para revisar artículos
    Muestra todos los artículos EN_REVISION y permite filtrar
    """
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    
    # Verificar rol
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto,
        rol_proyecto__in=['SUPERVISOR', 'DUEÑO']
    ).first()
    
    if not usuario_proyecto:
        messages.error(request, 'No tienes acceso a la bandeja de revisión.')
        return redirect('articulos:ver_articulos', proyecto_id=proyecto_id)
    
    # Filtros
    estado_filtro = request.GET.get('estado', 'EN_REVISION')
    usuario_filtro = request.GET.get('usuario', '')
    
    # Base query
    articulos = Articulo.objects.filter(proyecto=proyecto)
    
    # Aplicar filtros
    if estado_filtro:
        articulos = articulos.filter(estado=estado_filtro)
    
    if usuario_filtro:
        articulos = articulos.filter(
            Q(usuario_asignado_id=usuario_filtro) | Q(usuario_carga_id=usuario_filtro)
        )
    
    # Prefetch relacionados y anotar estadísticas
    articulos = articulos.select_related(
        'usuario_carga', 'usuario_asignado'
    ).prefetch_related(
        'campos_asignados__campo'
    ).annotate(
        total_campos=Count('campos_asignados'),
        campos_completados_count=Count('campos_asignados', filter=Q(campos_asignados__completado=True)),
        campos_aprobados_count=Count('campos_asignados', filter=Q(campos_asignados__aprobado=True))
    ).order_by('-fecha_actualizacion')
    
    # Calcular estadísticas
    total_en_revision = Articulo.objects.filter(
        proyecto=proyecto,
        estado='EN_REVISION'
    ).count()
    
    total_en_proceso = Articulo.objects.filter(
        proyecto=proyecto,
        estado='EN_PROCESO'
    ).count()
    
    total_aprobados = Articulo.objects.filter(
        proyecto=proyecto,
        estado='APROBADO'
    ).count()
    
    # Obtener colaboradores del proyecto
    colaboradores = UsuarioProyecto.objects.filter(
        proyecto=proyecto
    ).select_related('usuario').order_by('usuario__first_name')
    
    context = {
        'proyecto': proyecto,
        'articulos': articulos,
        'usuario_proyecto': usuario_proyecto,
        'estado_filtro': estado_filtro,
        'usuario_filtro': usuario_filtro,
        'total_en_revision': total_en_revision,
        'total_en_proceso': total_en_proceso,
        'total_aprobados': total_aprobados,
        'colaboradores': colaboradores,
    }
    
    return render(request, 'bandeja_revision.html', context)


@login_required
def estadisticas_articulo(request, articulo_id):
    """
    Vista AJAX que retorna estadísticas actualizadas del artículo
    Útil para actualizaciones en tiempo real sin recargar página
    """
    articulo = get_object_or_404(Articulo, id=articulo_id)
    
    # Verificar acceso
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=articulo.proyecto
    ).first()
    
    if not usuario_proyecto:
        return JsonResponse({'success': False, 'error': 'No tienes acceso'}, status=403)
    
    # Calcular estadísticas
    total_campos = articulo.campos_asignados.count()
    campos_completados = articulo.campos_asignados.filter(completado=True).count()
    campos_aprobados = articulo.campos_asignados.filter(aprobado=True).count()
    campos_pendientes = total_campos - campos_completados
    
    progreso_completado = (campos_completados / total_campos * 100) if total_campos > 0 else 0
    progreso_aprobado = (campos_aprobados / campos_completados * 100) if campos_completados > 0 else 0
    
    return JsonResponse({
        'success': True,
        'estado': articulo.estado,
        'estado_display': articulo.get_estado_display(),
        'total_campos': total_campos,
        'campos_completados': campos_completados,
        'campos_aprobados': campos_aprobados,
        'campos_pendientes': campos_pendientes,
        'progreso_completado': round(progreso_completado, 1),
        'progreso_aprobado': round(progreso_aprobado, 1),
        'puede_aprobar_completo': articulo.puede_aprobar_articulo(),
        'fecha_actualizacion': articulo.fecha_actualizacion.strftime('%d/%m/%Y %H:%M')
    })


# ==================== VISTAS DE ESTADÍSTICAS Y ANÁLISIS ====================


# ==================== MI PROGRESO (USUARIO INDIVIDUAL) ====================

@login_required
def mi_progreso(request, proyecto_id):
    """
    📊 Dashboard personal del usuario con Forest Plot interactivo
    Muestra progreso detallado de cada artículo y campo asignado
    """
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto
    ).first()
    
    if not usuario_proyecto:
        messages.error(request, 'No tienes acceso a este proyecto.')
        return redirect('mis_proyectos')
    
    # Artículos del usuario
    mis_articulos = Articulo.objects.filter(
        proyecto=proyecto
    ).filter(
        Q(usuario_asignado=request.user) | Q(usuario_carga=request.user)
    ).distinct()
    
    total_articulos = mis_articulos.count()
    
    # Por estado
    articulos_pendientes = mis_articulos.filter(estado='PENDIENTE').count()
    articulos_en_proceso = mis_articulos.filter(estado='EN_PROCESO').count()
    articulos_en_revision = mis_articulos.filter(estado='EN_REVISION').count()
    articulos_aprobados = mis_articulos.filter(estado='APROBADO').count()
    articulos_en_espera = mis_articulos.filter(estado='EN_ESPERA').count()
    
    # Campos
    mis_asignaciones = AsignacionCampo.objects.filter(
        articulo__in=mis_articulos
    ).select_related('campo', 'articulo')
    
    total_campos_asignados = mis_asignaciones.count()
    campos_completados = mis_asignaciones.filter(completado=True).count()
    campos_aprobados = mis_asignaciones.filter(aprobado=True).count()
    campos_pendientes = total_campos_asignados - campos_completados
    
    porcentaje_completado = round((campos_completados / total_campos_asignados * 100), 1) if total_campos_asignados > 0 else 0
    porcentaje_aprobado = round((campos_aprobados / campos_completados * 100), 1) if campos_completados > 0 else 0
    
    # ==================== DATOS PARA FOREST PLOT ====================
    forest_plot_data = []
    
    for articulo in mis_articulos.order_by('-fecha_actualizacion')[:20]:
        total_campos = articulo.campos_asignados.count()
        if total_campos == 0:
            continue
            
        campos_comp = articulo.campos_asignados.filter(completado=True).count()
        campos_aprob = articulo.campos_asignados.filter(aprobado=True).count()
        campos_pend = total_campos - campos_comp
        
        progreso_completado = (campos_comp / total_campos * 100) if total_campos > 0 else 0
        progreso_aprobado = (campos_aprob / total_campos * 100) if total_campos > 0 else 0
        progreso_pendiente = (campos_pend / total_campos * 100) if total_campos > 0 else 0
        
        titulo_corto = (articulo.titulo[:37] + '...') if len(articulo.titulo) > 40 else articulo.titulo
        
        forest_plot_data.append({
            'articulo_id': articulo.id,
            'titulo': titulo_corto,
            'titulo_completo': articulo.titulo,
            'total_campos': total_campos,
            'completados': campos_comp,
            'aprobados': campos_aprob,
            'pendientes': campos_pend,
            'progreso_completado': round(progreso_completado, 1),
            'progreso_aprobado': round(progreso_aprobado, 1),
            'progreso_pendiente': round(progreso_pendiente, 1),
            'estado': articulo.estado,
            'estado_display': articulo.get_estado_display(),
        })
    
    # ==================== CAMPOS POR CATEGORÍA ====================
    campos_por_categoria = mis_asignaciones.values(
        'campo__categoria'
    ).annotate(
        total=Count('id'),
        completados=Count('id', filter=Q(completado=True)),
        aprobados=Count('id', filter=Q(aprobado=True))
    ).order_by('campo__categoria')
    
    categorias_dict = dict(CampoMetanalisis.CATEGORIA_CHOICES)
    categorias_labels = []
    categorias_completados = []
    categorias_pendientes = []
    categorias_aprobados = []
    
    for item in campos_por_categoria:
        categoria_nombre = categorias_dict.get(item['campo__categoria'], item['campo__categoria'])
        categorias_labels.append(categoria_nombre)
        categorias_completados.append(item['completados'])
        categorias_pendientes.append(item['total'] - item['completados'])
        categorias_aprobados.append(item['aprobados'])
    
    # ==================== TOP 10 CAMPOS MÁS USADOS (REUTILIZADO) ====================
    mis_campos_mas_usados = mis_asignaciones.values(
        'campo__nombre', 'campo__categoria'
    ).annotate(
        total_asignaciones=Count('id'),
        completadas=Count('id', filter=Q(completado=True)),
        aprobadas=Count('id', filter=Q(aprobado=True))
    ).order_by('-total_asignaciones')[:10]
    
    top_campos_nombres = []
    top_campos_total = []
    top_campos_completadas = []
    top_campos_aprobadas = []
    top_campos_tasa = []
    
    for campo in mis_campos_mas_usados:
        top_campos_nombres.append(campo['campo__nombre'][:30])
        top_campos_total.append(campo['total_asignaciones'])
        top_campos_completadas.append(campo['completadas'])
        top_campos_aprobadas.append(campo['aprobadas'])
        tasa = round((campo['completadas'] / campo['total_asignaciones'] * 100), 1) if campo['total_asignaciones'] > 0 else 0
        top_campos_tasa.append(tasa)
    
    # ==================== ACTIVIDAD RECIENTE ====================
    actividad_reciente = HistorialArticulo.objects.filter(
        articulo__in=mis_articulos
    ).select_related('articulo', 'usuario').order_by('-fecha_cambio')[:15]
    
    # ==================== COMENTARIOS RECIENTES ====================
    comentarios_recientes = ComentarioRevision.objects.filter(
        articulo__in=mis_articulos
    ).select_related('articulo', 'supervisor', 'colaborador').order_by('-fecha_comentario')[:10]
    
    # ==================== ARTÍCULOS QUE REQUIEREN ATENCIÓN ====================
    articulos_con_correcciones = mis_articulos.filter(
        comentarios_revision__tipo_accion='CORRECCION',
        comentarios_revision__fecha_comentario__gte=timezone.now() - timedelta(days=7)
    ).distinct().order_by('-fecha_actualizacion')[:5]
    
    articulos_listos_revision = []
    for articulo in mis_articulos.filter(estado__in=['PENDIENTE', 'EN_PROCESO']):
        total = articulo.campos_asignados.count()
        completados = articulo.campos_asignados.filter(completado=True).count()
        if total > 0 and completados == total:
            articulos_listos_revision.append(articulo)
    
    # ==================== PREPARAR DATOS JSON ====================
    chart_data = {
        'forest_plot': {
            'articulos': json.dumps([item['titulo'] for item in forest_plot_data]),
            'completados': json.dumps([item['completados'] for item in forest_plot_data]),
            'aprobados': json.dumps([item['aprobados'] for item in forest_plot_data]),
            'pendientes': json.dumps([item['pendientes'] for item in forest_plot_data]),
            'total_campos': json.dumps([item['total_campos'] for item in forest_plot_data]),
            'titulos_completos': json.dumps([item['titulo_completo'] for item in forest_plot_data]),
            'estados': json.dumps([item['estado_display'] for item in forest_plot_data]),
        },
        'categorias': {
            'labels': json.dumps(categorias_labels) if categorias_labels else json.dumps([]),
            'completados': json.dumps(categorias_completados) if categorias_completados else json.dumps([]),
            'pendientes': json.dumps(categorias_pendientes) if categorias_pendientes else json.dumps([]),
            'aprobados': json.dumps(categorias_aprobados) if categorias_aprobados else json.dumps([])
        },
        'top_campos': {
            'nombres': json.dumps(top_campos_nombres),
            'total': json.dumps(top_campos_total),
            'completadas': json.dumps(top_campos_completadas),
            'aprobadas': json.dumps(top_campos_aprobadas),
            'tasa_completado': json.dumps(top_campos_tasa)
        },
        'resumen': {
            'estados_labels': json.dumps(['Pendiente', 'En Proceso', 'En Revisión', 'Aprobado', 'En Espera']),
            'estados_data': json.dumps([
                articulos_pendientes, 
                articulos_en_proceso, 
                articulos_en_revision, 
                articulos_aprobados, 
                articulos_en_espera
            ]),
        }
    }

    # IMPORTANTE: Agregar logging para debug
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"🔍 Forest plot data count: {len(forest_plot_data)}")
    logger.info(f"🔍 Categorías count: {len(categorias_labels)}")
    logger.info(f"🔍 Top campos count: {len(top_campos_nombres)}")

    context = {
        'proyecto': proyecto,
        'usuario_proyecto': usuario_proyecto,
        'total_articulos': total_articulos,
        'articulos_pendientes': articulos_pendientes,
        'articulos_en_proceso': articulos_en_proceso,
        'articulos_en_revision': articulos_en_revision,
        'articulos_aprobados': articulos_aprobados,
        'articulos_en_espera': articulos_en_espera,
        'total_campos_asignados': total_campos_asignados,
        'campos_completados': campos_completados,
        'campos_aprobados': campos_aprobados,
        'campos_pendientes': campos_pendientes,
        'porcentaje_completado': porcentaje_completado,
        'porcentaje_aprobado': porcentaje_aprobado,
        'chart_data': chart_data,
        'forest_plot_data': forest_plot_data,
        'mis_campos_mas_usados': mis_campos_mas_usados,  # Para la tabla
        'actividad_reciente': actividad_reciente,
        'comentarios_recientes': comentarios_recientes,
        'articulos_con_correcciones': articulos_con_correcciones,
        'articulos_listos_revision': articulos_listos_revision,
    }

    return render(request, 'mi_progreso.html', context)


# ==================== ESTADÍSTICAS DEL PROYECTO ====================

@login_required
def estadisticas_proyecto(request, proyecto_id):
    """
    📈 Dashboard de estadísticas generales del proyecto con gráficos profesionales
    """
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto,
        rol_proyecto__in=['SUPERVISOR', 'DUEÑO']
    ).first()
    
    if not usuario_proyecto:
        messages.error(request, 'No tienes permisos para ver las estadísticas del proyecto.')
        return redirect('articulos:ver_articulos', proyecto_id=proyecto_id)
    
    # ==================== ESTADÍSTICAS GENERALES ====================
    todos_articulos = Articulo.objects.filter(proyecto=proyecto)
    total_articulos = todos_articulos.count()
    
    articulos_en_espera = todos_articulos.filter(estado='EN_ESPERA').count()
    articulos_pendientes = todos_articulos.filter(estado='PENDIENTE').count()
    articulos_en_proceso = todos_articulos.filter(estado='EN_PROCESO').count()
    articulos_en_revision = todos_articulos.filter(estado='EN_REVISION').count()
    articulos_aprobados = todos_articulos.filter(estado='APROBADO').count()
    
    porcentaje_aprobados = round((articulos_aprobados / total_articulos * 100), 1) if total_articulos > 0 else 0
    porcentaje_en_proceso = round(((articulos_en_proceso + articulos_en_revision) / total_articulos * 100), 1) if total_articulos > 0 else 0
    
    # ==================== ESTADÍSTICAS DE CAMPOS ====================
    todas_asignaciones = AsignacionCampo.objects.filter(articulo__proyecto=proyecto)
    total_asignaciones = todas_asignaciones.count()
    asignaciones_completadas = todas_asignaciones.filter(completado=True).count()
    asignaciones_aprobadas = todas_asignaciones.filter(aprobado=True).count()
    asignaciones_pendientes = total_asignaciones - asignaciones_completadas
    
    porcentaje_campos_completados = round((asignaciones_completadas / total_asignaciones * 100), 1) if total_asignaciones > 0 else 0
    porcentaje_campos_aprobados = round((asignaciones_aprobadas / asignaciones_completadas * 100), 1) if asignaciones_completadas > 0 else 0
    
    # ==================== GRÁFICO DE DISTRIBUCIÓN DE ESTADOS ====================
    estados_labels = ['En Espera', 'Pendiente', 'En Proceso', 'En Revisión', 'Aprobado']
    estados_data = [articulos_en_espera, articulos_pendientes, articulos_en_proceso, articulos_en_revision, articulos_aprobados]
    estados_porcentajes = []
    for valor in estados_data:
        porcentaje = round((valor / total_articulos * 100), 1) if total_articulos > 0 else 0
        estados_porcentajes.append(porcentaje)
    
    # ==================== GRÁFICO DE CAMPOS POR CATEGORÍA ====================
    campos_por_categoria = todas_asignaciones.values(
        'campo__categoria'
    ).annotate(
        total=Count('id'),
        completados=Count('id', filter=Q(completado=True)),
        aprobados=Count('id', filter=Q(aprobado=True)),
        pendientes=Count('id', filter=Q(completado=False))
    ).order_by('-total')
    
    categorias_dict = dict(CampoMetanalisis.CATEGORIA_CHOICES)
    categorias_labels = []
    categorias_total = []
    categorias_completados = []
    categorias_aprobados = []
    categorias_pendientes = []
    
    for item in campos_por_categoria:
        categoria_nombre = categorias_dict.get(item['campo__categoria'], item['campo__categoria'])
        categorias_labels.append(categoria_nombre)
        categorias_total.append(item['total'])
        categorias_completados.append(item['completados'])
        categorias_aprobados.append(item['aprobados'])
        categorias_pendientes.append(item['pendientes'])
    
    # ==================== CAMPOS MÁS USADOS (TOP 10) ====================
    campos_mas_usados = todas_asignaciones.values(
        'campo__nombre', 'campo__categoria'
    ).annotate(
        total_asignaciones=Count('id'),
        completadas=Count('id', filter=Q(completado=True)),
        aprobadas=Count('id', filter=Q(aprobado=True))
    ).order_by('-total_asignaciones')[:10]
    
    top_campos_nombres = []
    top_campos_total = []
    top_campos_completadas = []
    top_campos_aprobadas = []
    top_campos_tasa = []
    
    for campo in campos_mas_usados:
        top_campos_nombres.append(campo['campo__nombre'][:30])
        top_campos_total.append(campo['total_asignaciones'])
        top_campos_completadas.append(campo['completadas'])
        top_campos_aprobadas.append(campo['aprobadas'])
        tasa = round((campo['completadas'] / campo['total_asignaciones'] * 100), 1) if campo['total_asignaciones'] > 0 else 0
        top_campos_tasa.append(tasa)
    
    # ==================== TIMELINE DE PROGRESO (últimos 30 días) ====================
    fecha_inicio = timezone.now() - timedelta(days=30)
    
    timeline_cambios = HistorialArticulo.objects.filter(
        articulo__proyecto=proyecto,
        fecha_cambio__gte=fecha_inicio
    ).extra(
        select={'dia': 'DATE(fecha_cambio)'}
    ).values('dia').annotate(
        total_cambios=Count('id'),
        aprobaciones=Count('id', filter=Q(tipo_cambio='APROBACION')),
        asignaciones=Count('id', filter=Q(tipo_cambio='ASIGNACION')),
        actualizaciones=Count('id', filter=Q(tipo_cambio='ACTUALIZACION'))
    ).order_by('dia')
    
    timeline_fechas = []
    timeline_aprobaciones = []
    timeline_asignaciones = []
    timeline_actualizaciones = []
    timeline_total = []
    
    for item in timeline_cambios:
        # El 'dia' ya es string cuando viene de .extra(), no necesita strftime
        dia_str = item['dia']
        if isinstance(dia_str, str):
            timeline_fechas.append(dia_str)
        else:
            timeline_fechas.append(dia_str.strftime('%Y-%m-%d'))
        timeline_aprobaciones.append(item['aprobaciones'])
        timeline_asignaciones.append(item['asignaciones'])
        timeline_actualizaciones.append(item['actualizaciones'])
        timeline_total.append(item['total_cambios'])
    
    # ==================== DISTRIBUCIÓN POR ARCHIVO BIB ====================
    articulos_por_archivo = todos_articulos.exclude(
        Q(archivo_bib__isnull=True) | Q(archivo_bib='')
    ).values('archivo_bib').annotate(
        total=Count('id'),
        aprobados=Count('id', filter=Q(estado='APROBADO')),
        en_proceso=Count('id', filter=Q(estado__in=['EN_PROCESO', 'EN_REVISION'])),
        pendientes=Count('id', filter=Q(estado='PENDIENTE'))
    ).order_by('-total')[:10]
    
    archivos_nombres = []
    archivos_total = []
    archivos_aprobados = []
    archivos_en_proceso = []
    archivos_pendientes = []
    
    for archivo in articulos_por_archivo:
        nombre_corto = archivo['archivo_bib'][:30] if archivo['archivo_bib'] else 'Sin archivo'
        archivos_nombres.append(nombre_corto)
        archivos_total.append(archivo['total'])
        archivos_aprobados.append(archivo['aprobados'])
        archivos_en_proceso.append(archivo['en_proceso'])
        archivos_pendientes.append(archivo['pendientes'])
    
    # ==================== ACTIVIDAD RECIENTE ====================
    actividad_proyecto = HistorialArticulo.objects.filter(
        articulo__proyecto=proyecto
    ).select_related('articulo', 'usuario').order_by('-fecha_cambio')[:20]
    
    # ==================== PREPARAR DATOS JSON (IGUAL QUE MI_PROGRESO) ====================
    chart_data = {
        'estados': {
            'labels': json.dumps(estados_labels),
            'data': json.dumps(estados_data),
            'porcentajes': json.dumps(estados_porcentajes)
        },
        'categorias': {
            'labels': json.dumps(categorias_labels),
            'total': json.dumps(categorias_total),
            'completados': json.dumps(categorias_completados),
            'aprobados': json.dumps(categorias_aprobados),
            'pendientes': json.dumps(categorias_pendientes)
        },
        'top_campos': {
            'nombres': json.dumps(top_campos_nombres),
            'total': json.dumps(top_campos_total),
            'completadas': json.dumps(top_campos_completadas),
            'aprobadas': json.dumps(top_campos_aprobadas),
            'tasa_completado': json.dumps(top_campos_tasa)
        },
        'timeline': {
            'fechas': json.dumps(timeline_fechas),
            'aprobaciones': json.dumps(timeline_aprobaciones),
            'asignaciones': json.dumps(timeline_asignaciones),
            'actualizaciones': json.dumps(timeline_actualizaciones),
            'total': json.dumps(timeline_total)
        },
        'archivos': {
            'nombres': json.dumps(archivos_nombres),
            'total': json.dumps(archivos_total),
            'aprobados': json.dumps(archivos_aprobados),
            'en_proceso': json.dumps(archivos_en_proceso),
            'pendientes': json.dumps(archivos_pendientes)
        }
    }
    
    context = {
        'proyecto': proyecto,
        'usuario_proyecto': usuario_proyecto,
        'total_articulos': total_articulos,
        'articulos_en_espera': articulos_en_espera,
        'articulos_pendientes': articulos_pendientes,
        'articulos_en_proceso': articulos_en_proceso,
        'articulos_en_revision': articulos_en_revision,
        'articulos_aprobados': articulos_aprobados,
        'porcentaje_aprobados': porcentaje_aprobados,
        'porcentaje_en_proceso': porcentaje_en_proceso,
        'total_asignaciones': total_asignaciones,
        'asignaciones_completadas': asignaciones_completadas,
        'asignaciones_aprobadas': asignaciones_aprobadas,
        'asignaciones_pendientes': asignaciones_pendientes,
        'porcentaje_campos_completados': porcentaje_campos_completados,
        'porcentaje_campos_aprobados': porcentaje_campos_aprobados,
        'chart_data': chart_data,
        'campos_mas_usados': campos_mas_usados,
        'actividad_proyecto': actividad_proyecto,
        'articulos_por_archivo': articulos_por_archivo,
    }
    
    return render(request, 'progreso_proyecto.html', context)


# ==================== ESTADÍSTICAS POR USUARIO ====================

@login_required
def estadisticas_por_usuario(request, proyecto_id):
    """
    👥 Estadísticas comparativas por usuario con gráficos de rendimiento
    """
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto,
        rol_proyecto__in=['SUPERVISOR', 'DUEÑO']
    ).first()
    
    if not usuario_proyecto:
        messages.error(request, 'No tienes permisos para ver estas estadísticas.')
        return redirect('articulos:ver_articulos', proyecto_id=proyecto_id)
    
    # ==================== OBTENER COLABORADORES ====================
    colaboradores = UsuarioProyecto.objects.filter(
        proyecto=proyecto
    ).select_related('usuario').order_by('usuario__first_name')
    
    # ==================== CALCULAR ESTADÍSTICAS POR USUARIO ====================
    estadisticas_usuarios = []
    
    for collab in colaboradores:
        usuario = collab.usuario
        
        articulos_usuario = Articulo.objects.filter(
            proyecto=proyecto
        ).filter(
            Q(usuario_asignado=usuario) | Q(usuario_carga=usuario)
        ).distinct()
        
        total_articulos = articulos_usuario.count()
        
        if total_articulos == 0:
            continue
        
        aprobados = articulos_usuario.filter(estado='APROBADO').count()
        en_revision = articulos_usuario.filter(estado='EN_REVISION').count()
        en_proceso = articulos_usuario.filter(estado='EN_PROCESO').count()
        pendientes = articulos_usuario.filter(estado='PENDIENTE').count()
        en_espera = articulos_usuario.filter(estado='EN_ESPERA').count()
        
        asignaciones = AsignacionCampo.objects.filter(articulo__in=articulos_usuario)
        total_campos = asignaciones.count()
        campos_completados = asignaciones.filter(completado=True).count()
        campos_aprobados = asignaciones.filter(aprobado=True).count()
        campos_pendientes = total_campos - campos_completados
        
        porcentaje_aprobados = round((aprobados / total_articulos * 100), 1) if total_articulos > 0 else 0
        porcentaje_campos_completados = round((campos_completados / total_campos * 100), 1) if total_campos > 0 else 0
        
        fecha_hace_7_dias = timezone.now() - timedelta(days=7)
        actividad_reciente = HistorialArticulo.objects.filter(
            articulo__in=articulos_usuario,
            usuario=usuario,
            fecha_cambio__gte=fecha_hace_7_dias
        ).count()
        
        estadisticas_usuarios.append({
            'usuario': usuario,
            'usuario_nombre': f"{usuario.first_name} {usuario.last_name}" if usuario.first_name else usuario.username,
            'rol': collab.get_rol_proyecto_display(),
            'total_articulos': total_articulos,
            'aprobados': aprobados,
            'en_revision': en_revision,
            'en_proceso': en_proceso,
            'pendientes': pendientes,
            'en_espera': en_espera,
            'total_campos': total_campos,
            'campos_completados': campos_completados,
            'campos_aprobados': campos_aprobados,
            'campos_pendientes': campos_pendientes,
            'porcentaje_aprobados': porcentaje_aprobados,
            'porcentaje_campos_completados': porcentaje_campos_completados,
            'actividad_reciente': actividad_reciente,
        })
    
    estadisticas_usuarios.sort(key=lambda x: x['porcentaje_aprobados'], reverse=True)
    
    # ==================== GRÁFICOS COMPARATIVOS ====================
    usuarios_nombres = []
    comparativa_aprobados = []
    comparativa_en_revision = []
    comparativa_en_proceso = []
    comparativa_pendientes = []
    
    campos_usuarios_nombres = []
    campos_completados_data = []
    campos_pendientes_data = []
    campos_porcentaje_data = []
    
    rendimiento_usuarios = []
    rendimiento_articulos = []
    rendimiento_campos = []
    
    for stats in estadisticas_usuarios[:10]:  # Top 10 usuarios
        nombre_corto = stats['usuario_nombre'][:20]
        
        usuarios_nombres.append(nombre_corto)
        comparativa_aprobados.append(stats['aprobados'])
        comparativa_en_revision.append(stats['en_revision'])
        comparativa_en_proceso.append(stats['en_proceso'])
        comparativa_pendientes.append(stats['pendientes'])
        
        campos_usuarios_nombres.append(nombre_corto)
        campos_completados_data.append(stats['campos_completados'])
        campos_pendientes_data.append(stats['campos_pendientes'])
        campos_porcentaje_data.append(stats['porcentaje_campos_completados'])
        
        rendimiento_usuarios.append(nombre_corto)
        rendimiento_articulos.append(stats['porcentaje_aprobados'])
        rendimiento_campos.append(stats['porcentaje_campos_completados'])
    
    # ==================== ESTADÍSTICAS COMPARATIVAS ====================
    if estadisticas_usuarios:
        promedio_articulos_aprobados = sum(u['porcentaje_aprobados'] for u in estadisticas_usuarios) / len(estadisticas_usuarios)
        promedio_campos_completados = sum(u['porcentaje_campos_completados'] for u in estadisticas_usuarios) / len(estadisticas_usuarios)
        total_actividad_7_dias = sum(u['actividad_reciente'] for u in estadisticas_usuarios)
    else:
        promedio_articulos_aprobados = 0
        promedio_campos_completados = 0
        total_actividad_7_dias = 0
    
    # ==================== PREPARAR DATOS JSON (IGUAL QUE MI_PROGRESO) ====================
    chart_data = {
        'comparativa_articulos': {
            'usuarios': json.dumps(usuarios_nombres),
            'aprobados': json.dumps(comparativa_aprobados),
            'en_revision': json.dumps(comparativa_en_revision),
            'en_proceso': json.dumps(comparativa_en_proceso),
            'pendientes': json.dumps(comparativa_pendientes)
        },
        'comparativa_campos': {
            'usuarios': json.dumps(campos_usuarios_nombres),
            'completados': json.dumps(campos_completados_data),
            'pendientes': json.dumps(campos_pendientes_data),
            'porcentaje': json.dumps(campos_porcentaje_data)
        },
        'rendimiento': {
            'usuarios': json.dumps(rendimiento_usuarios),
            'porcentaje_aprobados': json.dumps(rendimiento_articulos),
            'porcentaje_campos': json.dumps(rendimiento_campos)
        }
    }
    
    context = {
        'proyecto': proyecto,
        'usuario_proyecto': usuario_proyecto,
        'estadisticas_usuarios': estadisticas_usuarios,
        'total_colaboradores': len(estadisticas_usuarios),
        'promedio_articulos_aprobados': round(promedio_articulos_aprobados, 1),
        'promedio_campos_completados': round(promedio_campos_completados, 1),
        'total_actividad_7_dias': total_actividad_7_dias,
        'chart_data': chart_data,
    }
    
    return render(request, 'estadisticas_usuarios.html', context)


# ==================== EXPORTAR ESTADÍSTICAS ====================

@login_required
def exportar_estadisticas_json(request, proyecto_id):
    """
    📥 Exporta estadísticas del proyecto en formato JSON
    """
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto,
        rol_proyecto__in=['SUPERVISOR', 'DUEÑO']
    ).first()
    
    if not usuario_proyecto:
        return JsonResponse({'error': 'No tienes permisos'}, status=403)
    
    todos_articulos = Articulo.objects.filter(proyecto=proyecto)
    todas_asignaciones = AsignacionCampo.objects.filter(articulo__proyecto=proyecto)
    
    estadisticas = {
        'proyecto': {
            'id': proyecto.id,
            'nombre': proyecto.nombre,
            'fecha_generacion': timezone.now().isoformat(),
        },
        'articulos': {
            'total': todos_articulos.count(),
            'en_espera': todos_articulos.filter(estado='EN_ESPERA').count(),
            'pendientes': todos_articulos.filter(estado='PENDIENTE').count(),
            'en_proceso': todos_articulos.filter(estado='EN_PROCESO').count(),
            'en_revision': todos_articulos.filter(estado='EN_REVISION').count(),
            'aprobados': todos_articulos.filter(estado='APROBADO').count(),
        },
        'campos': {
            'total_asignaciones': todas_asignaciones.count(),
            'completadas': todas_asignaciones.filter(completado=True).count(),
            'aprobadas': todas_asignaciones.filter(aprobado=True).count(),
            'pendientes': todas_asignaciones.filter(completado=False).count(),
        }
    }
    
    return JsonResponse(estadisticas, json_dumps_params={'indent': 2})

@login_required
def editar_plantilla_proyecto(request, proyecto_id):
    """Vista para editar la plantilla del proyecto (DUEÑO y SUPERVISOR)"""
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto,
        rol_proyecto__in=['DUEÑO', 'SUPERVISOR']
    ).first()
    
    if not usuario_proyecto:
        usuario_rol = UsuarioProyecto.objects.filter(
            usuario=request.user,
            proyecto=proyecto
        ).first()
        rol_actual = usuario_rol.rol_proyecto if usuario_rol else 'Sin acceso'
        messages.error(
            request, 
            f'⛔ No tienes permiso para editar la plantilla. '
            f'Solo el Dueño y Supervisor del proyecto pueden modificar variables. (Tu rol: {rol_actual})'
        )
        return redirect('articulos:ver_plantilla_proyecto', proyecto_id=proyecto_id)
    
    plantilla = PlantillaBusqueda.objects.filter(
        proyecto=proyecto,
        es_predeterminada=True
    ).prefetch_related('campos').first()
    
    if not plantilla:
        messages.error(request, 'Este proyecto no tiene plantilla. Contacta al administrador.')
        return redirect('detalle_proyecto', proyecto_id=proyecto_id)
    
    if request.method == 'POST':
        accion = request.POST.get('accion')
        
        # AGREGAR CAMPOS
        if accion == 'agregar_campos':
            campos_ids = request.POST.getlist('campos_agregar')
            
            if not campos_ids:
                messages.warning(request, 'Debes seleccionar al menos un campo.')
            else:
                campos_agregados = 0
                articulos_actualizados = 0
                
                with transaction.atomic():
                    for campo_id in campos_ids:
                        campo = get_object_or_404(CampoMetanalisis, id=campo_id)
                        
                        if campo not in plantilla.campos.all():
                            plantilla.campos.add(campo)
                            campos_agregados += 1
                            
                            articulos = Articulo.objects.filter(proyecto=proyecto)
                            
                            for articulo in articulos:
                                if not AsignacionCampo.objects.filter(articulo=articulo, campo=campo).exists():
                                    AsignacionCampo.objects.create(
                                        articulo=articulo,
                                        campo=campo,
                                        asignado_por=request.user
                                    )
                                    articulos_actualizados += 1
                                    
                                    if articulo.estado == 'EN_ESPERA':
                                        articulo.cambiar_estado('PENDIENTE', usuario=request.user)
                                    elif articulo.estado == 'APROBADO':
                                        articulo.cambiar_estado('PENDIENTE', usuario=request.user)
                                        
                                        colaborador = articulo.usuario_asignado or articulo.usuario_carga
                                        if colaborador and colaborador != request.user:
                                            crear_notificacion_articulos(
                                                usuario=colaborador,
                                                tipo='tarea_asignada',
                                                titulo=f'Nuevas tareas en artículo aprobado - {proyecto.nombre}',
                                                mensaje=f'Se agregaron nuevos campos a la plantilla. Tu artículo "{articulo.titulo[:50]}..." requiere completar estas tareas.',
                                                url=reverse('articulos:workspace_articulo', args=[articulo.id]),
                                                proyecto=proyecto
                                            )
                
                if campos_agregados > 0:
                    messages.success(request, f'{campos_agregados} campo(s) agregados. {articulos_actualizados} artículos actualizados.')
                else:
                    messages.info(request, 'Los campos seleccionados ya estaban en la plantilla.')
                
                return redirect('articulos:editar_plantilla_proyecto', proyecto_id=proyecto_id)
        
        # CREAR CAMPO
        elif accion == 'crear_campo':
            nombre = request.POST.get('nombre')
            codigo = request.POST.get('codigo')
            categoria = request.POST.get('categoria')
            tipo_dato = request.POST.get('tipo_dato')
            descripcion = request.POST.get('descripcion', '')
            opciones = request.POST.get('opciones_validas', '')
            es_global = request.POST.get('es_global') == 'on'
            agregar_a_plantilla = request.POST.get('agregar_a_plantilla') == 'on'
            
            campo_existente = CampoMetanalisis.objects.filter(codigo=codigo).first()
            
            if campo_existente:
                if campo_existente.proyecto is None:
                    messages.error(
                        request, 
                        f'Ya existe una variable GLOBAL con el código "{codigo}". Puedes agregarla desde la lista de variables globales.'
                    )
                elif campo_existente.proyecto == proyecto:
                    messages.error(request, f'Ya existe una variable personalizada con el código "{codigo}" en este proyecto.')
                else:
                    messages.error(request, f'El código "{codigo}" está en uso por otro proyecto. Por favor elige otro código único.')
                return redirect('articulos:editar_plantilla_proyecto', proyecto_id=proyecto_id)
            
            if es_global:
                nombre_existente = CampoMetanalisis.objects.filter(
                    nombre__iexact=nombre,
                    proyecto__isnull=True
                ).exists()
                
                if nombre_existente:
                    messages.error(request, f'Ya existe una variable global llamada "{nombre}". Puedes agregarla desde la lista de variables globales.')
                    return redirect('articulos:editar_plantilla_proyecto', proyecto_id=proyecto_id)
            
            if not nombre or not codigo:
                messages.error(request, 'El nombre y código son obligatorios.')
            else:
                opciones_json = None
                if tipo_dato == 'OPCIONES' and opciones:
                    opciones_json = [opt.strip() for opt in opciones.split(',')]
                
                with transaction.atomic():
                    campo_proyecto = None if es_global else proyecto
                    tipo_campo = "global" if es_global else "personalizada"
                    
                    campo = CampoMetanalisis.objects.create(
                        nombre=nombre,
                        codigo=codigo,
                        categoria=categoria,
                        tipo_dato=tipo_dato,
                        descripcion=descripcion,
                        opciones_validas=opciones_json,
                        proyecto=campo_proyecto,
                        creado_por=request.user,
                        es_predefinido=False
                    )
                    
                    debe_agregar = (not es_global) or agregar_a_plantilla
                    
                    if debe_agregar:
                        plantilla.campos.add(campo)
                        
                        articulos = Articulo.objects.filter(proyecto=proyecto)
                        articulos_actualizados = 0
                        
                        for articulo in articulos:
                            if not AsignacionCampo.objects.filter(articulo=articulo, campo=campo).exists():
                                AsignacionCampo.objects.create(
                                    articulo=articulo,
                                    campo=campo,
                                    asignado_por=request.user
                                )
                                articulos_actualizados += 1
                                
                                if articulo.estado in ['EN_ESPERA', 'APROBADO']:
                                    articulo.cambiar_estado('PENDIENTE', usuario=request.user)
                        
                        mensaje_extra = f" y agregada a la plantilla. {articulos_actualizados} artículos actualizados."
                    else:
                        mensaje_extra = ". Ahora está disponible para todos los proyectos."
                    
                    messages.success(request, f'Variable {tipo_campo} "{nombre}" creada{mensaje_extra}')
                
                return redirect('articulos:editar_plantilla_proyecto', proyecto_id=proyecto_id)
        
        # QUITAR CAMPO
        elif accion == 'quitar_campo':
            campo_id = request.POST.get('campo_id')
            
            if campo_id:
                campo = get_object_or_404(CampoMetanalisis, id=campo_id)
                
                asignaciones_aprobadas = AsignacionCampo.objects.filter(
                    campo=campo,
                    articulo__proyecto=proyecto,
                    aprobado=True
                ).count()
                
                if asignaciones_aprobadas > 0:
                    messages.error(request, f'No puedes quitar "{campo.nombre}" porque hay {asignaciones_aprobadas} asignaciones aprobadas.')
                else:
                    with transaction.atomic():
                        plantilla.campos.remove(campo)
                        
                        asignaciones_eliminadas = AsignacionCampo.objects.filter(
                            campo=campo,
                            articulo__proyecto=proyecto,
                            aprobado=False
                        ).delete()[0]
                        
                        messages.success(request, f'Campo "{campo.nombre}" quitado. {asignaciones_eliminadas} asignaciones eliminadas.')
                    
                    return redirect('articulos:editar_plantilla_proyecto', proyecto_id=proyecto_id)
    
    # GET: Preparar datos
    from itertools import groupby
    from operator import attrgetter
    
    campos_en_plantilla = plantilla.campos.all()
    
    # Variables GLOBALES: sin proyecto asignado (proyecto__isnull=True)
    variables_globales = CampoMetanalisis.objects.filter(
        proyecto__isnull=True,
        activo=True
    ).order_by('categoria', 'nombre')
    
    # Variables PERSONALIZADAS: TODAS las que tienen proyecto asignado (cualquier proyecto)
    variables_personalizadas = CampoMetanalisis.objects.filter(
        proyecto__isnull=False,
        activo=True
    ).select_related('proyecto', 'creado_por').order_by('categoria', 'nombre')
    
    print(f"🔍 DEBUG editar_plantilla: Variables globales: {variables_globales.count()}")
    print(f"🔍 DEBUG editar_plantilla: Variables personalizadas: {variables_personalizadas.count()}")
    
    # Agrupar globales
    variables_globales_agrupadas = {}
    for categoria_key, items in groupby(variables_globales, key=attrgetter('categoria')):
        categoria_nombre = dict(CampoMetanalisis.CATEGORIA_CHOICES).get(categoria_key, categoria_key)
        items_list = list(items)
        
        items_con_estado = []
        for campo in items_list:
            en_plantilla = campo in campos_en_plantilla
            en_uso = AsignacionCampo.objects.filter(campo=campo, articulo__proyecto=proyecto).exists()
            
            items_con_estado.append({
                'campo': campo,
                'en_plantilla': en_plantilla,
                'en_uso': en_uso,
                'es_global': True,
                'creado_por_mi': campo.creado_por == request.user if campo.creado_por else False,
                'puede_eliminar': False
            })
        
        if items_con_estado:
            variables_globales_agrupadas[categoria_nombre] = items_con_estado
    
    # Agrupar personalizadas (TODAS, no solo del proyecto actual)
    variables_personalizadas_agrupadas = {}
    for categoria_key, items in groupby(variables_personalizadas, key=attrgetter('categoria')):
        categoria_nombre = dict(CampoMetanalisis.CATEGORIA_CHOICES).get(categoria_key, categoria_key)
        items_list = list(items)
        
        items_con_estado = []
        for campo in items_list:
            en_plantilla = campo in campos_en_plantilla
            en_uso = AsignacionCampo.objects.filter(campo=campo, articulo__proyecto=proyecto).exists()
            tiene_aprobados = AsignacionCampo.objects.filter(
                campo=campo, 
                articulo__proyecto=proyecto, 
                aprobado=True
            ).exists()
            
            es_de_este_proyecto = campo.proyecto == proyecto
            es_de_otro_proyecto = campo.proyecto and campo.proyecto != proyecto
            
            items_con_estado.append({
                'campo': campo,
                'en_plantilla': en_plantilla,
                'en_uso': en_uso,
                'tiene_aprobados': tiene_aprobados,
                'es_global': False,
                'creado_por_mi': campo.creado_por == request.user if campo.creado_por else False,
                'es_de_este_proyecto': es_de_este_proyecto,
                'es_de_otro_proyecto': es_de_otro_proyecto,
                'puede_eliminar': es_de_este_proyecto and not (en_uso or tiene_aprobados),
                'proyecto_origen': campo.proyecto.nombre if campo.proyecto else None
            })
        
        if items_con_estado:
            variables_personalizadas_agrupadas[categoria_nombre] = items_con_estado
    
    # Campos en plantilla
    campos_por_categoria = {}
    for campo in campos_en_plantilla.order_by('categoria', 'nombre'):
        categoria = campo.get_categoria_display()
        if categoria not in campos_por_categoria:
            campos_por_categoria[categoria] = []
        
        tiene_aprobados = AsignacionCampo.objects.filter(
            campo=campo,
            articulo__proyecto=proyecto,
            aprobado=True
        ).exists()
        
        campos_por_categoria[categoria].append({
            'campo': campo,
            'tiene_aprobados': tiene_aprobados,
            'es_global': campo.proyecto is None,
            'creado_por_mi': campo.creado_por == request.user if campo.creado_por else False
        })
    
    context = {
        'proyecto': proyecto,
        'plantilla': plantilla,
        'campos_por_categoria': campos_por_categoria,
        'variables_globales_agrupadas': variables_globales_agrupadas,
        'variables_personalizadas_agrupadas': variables_personalizadas_agrupadas,
        'categorias': CampoMetanalisis.CATEGORIA_CHOICES,
        'tipos_dato': CampoMetanalisis.TIPO_DATO_CHOICES,
        'total_articulos': Articulo.objects.filter(proyecto=proyecto).count(),
        'total_globales': variables_globales.count(),
        'total_personalizadas': variables_personalizadas.count(),
        'campos_en_plantilla_ids': list(campos_en_plantilla.values_list('id', flat=True)),
    }
    
    return render(request, 'editar_plantilla.html', context)

@login_required
def gestionar_variables_globales(request, proyecto_id):
    """Vista para gestionar variables GLOBALES y PERSONALIZADAS"""
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto,
        rol_proyecto='DUEÑO'
    ).first()
    
    if not usuario_proyecto:
        messages.error(request, 'Solo el Dueño puede gestionar variables.')
        return redirect('detalle_proyecto', proyecto_id=proyecto_id)
    
    plantilla = PlantillaBusqueda.objects.filter(
        proyecto=proyecto,
        es_predeterminada=True
    ).prefetch_related('campos').first()
    
    if not plantilla:
        messages.error(request, 'Este proyecto no tiene plantilla configurada.')
        return redirect('detalle_proyecto', proyecto_id=proyecto_id)
    
    # ============================================
    # POST: PROCESAR ACCIONES
    # ============================================
    if request.method == 'POST':
        accion = request.POST.get('accion')
        
        # ============================================
        # ACCIÓN 1: AGREGAR CAMPOS EXISTENTES A LA PLANTILLA
        # ============================================
        if accion == 'agregar_campos':
            campos_ids = request.POST.get('campos_agregar', '').split(',')
            
            if not campos_ids or not any(c.strip() for c in campos_ids):
                messages.warning(request, 'Debes seleccionar al menos un campo.')
            else:
                campos_agregados = 0
                articulos_actualizados = 0
                
                with transaction.atomic():
                    for campo_id in campos_ids:
                        if not campo_id.strip():
                            continue
                            
                        try:
                            campo = CampoMetanalisis.objects.get(id=campo_id.strip(), activo=True)
                            
                            # Agregar a plantilla si no está
                            if campo not in plantilla.campos.all():
                                plantilla.campos.add(campo)
                                campos_agregados += 1
                                
                                # Asignar a todos los artículos del proyecto
                                articulos = Articulo.objects.filter(proyecto=proyecto)
                                
                                for articulo in articulos:
                                    if not AsignacionCampo.objects.filter(articulo=articulo, campo=campo).exists():
                                        AsignacionCampo.objects.create(
                                            articulo=articulo,
                                            campo=campo,
                                            asignado_por=request.user
                                        )
                                        articulos_actualizados += 1
                                        
                                        # Cambiar estado si es necesario
                                        if articulo.estado in ['EN_ESPERA', 'APROBADO']:
                                            articulo.cambiar_estado('PENDIENTE', usuario=request.user)
                        
                        except CampoMetanalisis.DoesNotExist:
                            pass
                
                if campos_agregados > 0:
                    messages.success(
                        request, 
                        f'✅ {campos_agregados} campo(s) agregados a la plantilla. '
                        f'{articulos_actualizados} artículos actualizados.'
                    )
                else:
                    messages.info(request, 'Los campos seleccionados ya estaban en la plantilla.')
                
                return redirect("editar_plantilla_proyecto", proyecto_id=proyecto.id)
        
        # ============================================
        # ACCIÓN 2: QUITAR CAMPO DE LA PLANTILLA
        # ============================================
        elif accion == 'quitar_campo':
            campo_id = request.POST.get('campo_id')
            
            if campo_id:
                campo = get_object_or_404(CampoMetanalisis, id=campo_id)
                
                # Verificar si hay asignaciones aprobadas
                asignaciones_aprobadas = AsignacionCampo.objects.filter(
                    campo=campo,
                    articulo__proyecto=proyecto,
                    aprobado=True
                ).count()
                
                if asignaciones_aprobadas > 0:
                    messages.error(
                        request, 
                        f'No puedes quitar "{campo.nombre}" porque hay {asignaciones_aprobadas} asignaciones aprobadas.'
                    )
                else:
                    with transaction.atomic():
                        plantilla.campos.remove(campo)
                        
                        # Eliminar solo asignaciones no aprobadas
                        asignaciones_eliminadas = AsignacionCampo.objects.filter(
                            campo=campo,
                            articulo__proyecto=proyecto,
                            aprobado=False
                        ).delete()[0]
                        
                        messages.success(
                            request, 
                            f'✅ Campo "{campo.nombre}" quitado de la plantilla. '
                            f'{asignaciones_eliminadas} asignaciones eliminadas.'
                        )
                    
                    return redirect('articulos:gestionar_variables_globales', proyecto_id=proyecto_id)
        
        # ============================================
        # ACCIÓN 3: CREAR NUEVA VARIABLE
        # ============================================
        elif accion == 'crear_variable':
            nombre = request.POST.get('nombre', '').strip()
            codigo = request.POST.get('codigo', '').strip().lower()
            categoria = request.POST.get('categoria')
            tipo_dato = request.POST.get('tipo_dato')
            descripcion = request.POST.get('descripcion', '').strip()
            opciones = request.POST.get('opciones_validas', '').strip()
            es_global = request.POST.get('es_global') == 'on'
            
            # Validaciones básicas
            if not nombre or not codigo or not categoria or not tipo_dato:
                messages.error(request, '❌ Todos los campos obligatorios deben completarse.')
                return redirect('articulos:gestionar_variables_globales', proyecto_id=proyecto_id)
            
            try:
                # ============================================
                # VALIDACIÓN 1: Verificar código único
                # ============================================
                campo_existente = CampoMetanalisis.objects.filter(codigo=codigo).first()
                
                if campo_existente:
                    if campo_existente.proyecto is None:
                        messages.error(
                            request, 
                            f'❌ Ya existe una variable GLOBAL con el código "{codigo}". '
                            f'Puedes agregarla desde la pestaña "Globales del Sistema".'
                        )
                    elif campo_existente.proyecto == proyecto:
                        messages.error(
                            request, 
                            f'❌ Ya existe una variable personalizada con el código "{codigo}" en este proyecto.'
                        )
                    else:
                        messages.error(
                            request, 
                            f'❌ El código "{codigo}" está en uso por el proyecto "{campo_existente.proyecto.nombre}". '
                            f'Por favor elige otro código único.'
                        )
                    return redirect('articulos:gestionar_variables_globales', proyecto_id=proyecto_id)
                
                # ============================================
                # VALIDACIÓN 2: Verificar nombre único (solo para globales)
                # ============================================
                if es_global:
                    nombre_existente = CampoMetanalisis.objects.filter(
                        nombre__iexact=nombre,
                        proyecto__isnull=True
                    ).first()
                    
                    if nombre_existente:
                        messages.error(
                            request, 
                            f'❌ Ya existe una variable global llamada "{nombre}". '
                            f'Puedes agregarla desde la pestaña "Globales del Sistema".'
                        )
                        return redirect('articulos:gestionar_variables_globales', proyecto_id=proyecto_id)
                
                # ============================================
                # PROCESAR OPCIONES VÁLIDAS
                # ============================================
                opciones_json = None
                if tipo_dato == 'OPCIONES' and opciones:
                    opciones_json = [opt.strip() for opt in opciones.split(',') if opt.strip()]
                
                # ============================================
                # CREAR LA VARIABLE
                # ============================================
                with transaction.atomic():
                    campo_proyecto = None if es_global else proyecto
                    tipo_campo = "global" if es_global else "personalizada"
                    
                    campo = CampoMetanalisis.objects.create(
                        nombre=nombre,
                        codigo=codigo,
                        categoria=categoria,
                        tipo_dato=tipo_dato,
                        descripcion=descripcion,
                        opciones_validas=opciones_json,
                        proyecto=campo_proyecto,  # 🔥 None para global, proyecto para personalizada
                        creado_por=request.user,
                        es_predefinido=False,
                        activo=True
                    )
                    
                    # ============================================
                    # SI ES PERSONALIZADA: Agregar a plantilla y artículos
                    # ============================================
                    if not es_global:
                        # Agregar a la plantilla
                        plantilla.campos.add(campo)
                        
                        # Asignar a todos los artículos del proyecto
                        articulos = Articulo.objects.filter(proyecto=proyecto)
                        articulos_actualizados = 0
                        
                        for articulo in articulos:
                            if not AsignacionCampo.objects.filter(articulo=articulo, campo=campo).exists():
                                AsignacionCampo.objects.create(
                                    articulo=articulo,
                                    campo=campo,
                                    asignado_por=request.user
                                )
                                articulos_actualizados += 1
                                
                                # Cambiar estado si es necesario
                                if articulo.estado in ['EN_ESPERA', 'APROBADO']:
                                    articulo.cambiar_estado('PENDIENTE', usuario=request.user)
                        
                        messages.success(
                            request, 
                            f'Variable {tipo_campo} "{nombre}" creada y agregada a la plantilla. '
                            f'{articulos_actualizados} artículos actualizados.'
                        )
                    else:
                        messages.success(
                            request, 
                            f'✅ Variable {tipo_campo} "{nombre}" creada exitosamente. '
                            f'Ahora está disponible para todos los proyectos.'
                        )
                
                return redirect('articulos:gestionar_variables_globales', proyecto_id=proyecto_id)
                
            except Exception as e:
                messages.error(request, f'❌ Error al crear la variable: {str(e)}')
                return redirect('articulos:gestionar_variables_globales', proyecto_id=proyecto_id)
        
        # ============================================
        # ACCIÓN 4: ELIMINAR VARIABLE PERSONALIZADA
        # ============================================
        elif accion == 'eliminar_variable':
            campo_id = request.POST.get('campo_id')
            
            if campo_id:
                campo = get_object_or_404(CampoMetanalisis, id=campo_id)
                
                # Solo permite eliminar si es del proyecto actual
                if campo.proyecto != proyecto:
                    messages.error(
                        request, 
                        f'❌ Solo el proyecto "{campo.proyecto.nombre}" puede eliminar esta variable.'
                    )
                    return redirect('articulos:gestionar_variables_globales', proyecto_id=proyecto_id)
                
                # Verificar si tiene asignaciones aprobadas
                tiene_aprobados = AsignacionCampo.objects.filter(
                    campo=campo,
                    articulo__proyecto=proyecto,
                    aprobado=True
                ).exists()
                
                if tiene_aprobados:
                    messages.error(
                        request, 
                        f'❌ No puedes eliminar "{campo.nombre}" porque tiene datos aprobados.'
                    )
                else:
                    nombre_campo = campo.nombre
                    
                    with transaction.atomic():
                        # Eliminar asignaciones no aprobadas
                        AsignacionCampo.objects.filter(
                            campo=campo,
                            articulo__proyecto=proyecto,
                            aprobado=False
                        ).delete()
                        
                        # Quitar de plantilla
                        plantilla.campos.remove(campo)
                        
                        # Desactivar el campo
                        campo.activo = False
                        campo.save()
                    
                    messages.success(
                        request, 
                        f'✅ Variable "{nombre_campo}" eliminada del repositorio compartido.'
                    )
                
                return redirect('articulos:gestionar_variables_globales', proyecto_id=proyecto_id)
    
    # ============================================
    # GET: PREPARAR DATOS PARA LA VISTA
    # ============================================
    from itertools import groupby
    from operator import attrgetter
    
    campos_en_plantilla = plantilla.campos.all()
    
    # 🌍 Variables GLOBALES: sin proyecto asignado (proyecto__isnull=True)
    variables_globales = CampoMetanalisis.objects.filter(
        proyecto__isnull=True,
        activo=True
    ).order_by('categoria', 'nombre')
    
    # 👥 Variables PERSONALIZADAS: TODAS las que tienen proyecto asignado
    variables_personalizadas = CampoMetanalisis.objects.filter(
        proyecto__isnull=False,
        activo=True
    ).select_related('proyecto', 'creado_por').order_by('categoria', 'nombre')
    
    print(f"🔍 DEBUG: Variables globales encontradas: {variables_globales.count()}")
    print(f"🔍 DEBUG: Variables personalizadas encontradas: {variables_personalizadas.count()}")
    
    # ============================================
    # AGRUPAR VARIABLES GLOBALES POR CATEGORÍA
    # ============================================
    variables_globales_agrupadas = {}
    for categoria_key, items in groupby(variables_globales, key=attrgetter('categoria')):
        categoria_nombre = dict(CampoMetanalisis.CATEGORIA_CHOICES).get(categoria_key, categoria_key)
        items_list = list(items)
        
        items_con_estado = []
        for campo in items_list:
            en_plantilla = campo in campos_en_plantilla
            en_uso = AsignacionCampo.objects.filter(campo=campo, articulo__proyecto=proyecto).exists()
            
            items_con_estado.append({
                'campo': campo,
                'en_plantilla': en_plantilla,
                'en_uso': en_uso,
                'es_global': True,
                'creado_por_mi': campo.creado_por == request.user if campo.creado_por else False,
                'puede_eliminar': False
            })
        
        if items_con_estado:
            variables_globales_agrupadas[categoria_nombre] = items_con_estado
    
    # ============================================
    # AGRUPAR VARIABLES PERSONALIZADAS POR CATEGORÍA
    # ============================================
    variables_personalizadas_agrupadas = {}
    for categoria_key, items in groupby(variables_personalizadas, key=attrgetter('categoria')):
        categoria_nombre = dict(CampoMetanalisis.CATEGORIA_CHOICES).get(categoria_key, categoria_key)
        items_list = list(items)
        
        items_con_estado = []
        for campo in items_list:
            en_plantilla = campo in campos_en_plantilla
            en_uso = AsignacionCampo.objects.filter(campo=campo, articulo__proyecto=proyecto).exists()
            tiene_aprobados = AsignacionCampo.objects.filter(
                campo=campo, 
                articulo__proyecto=proyecto, 
                aprobado=True
            ).exists()
            
            es_de_este_proyecto = campo.proyecto == proyecto
            es_de_otro_proyecto = campo.proyecto and campo.proyecto != proyecto
            
            items_con_estado.append({
                'campo': campo,
                'en_plantilla': en_plantilla,
                'en_uso': en_uso,
                'tiene_aprobados': tiene_aprobados,
                'es_global': False,
                'creado_por_mi': campo.creado_por == request.user if campo.creado_por else False,
                'es_de_este_proyecto': es_de_este_proyecto,
                'es_de_otro_proyecto': es_de_otro_proyecto,
                'puede_eliminar': es_de_este_proyecto and not (en_uso or tiene_aprobados),
                'proyecto_origen': campo.proyecto.nombre if campo.proyecto else None
            })
        
        if items_con_estado:
            variables_personalizadas_agrupadas[categoria_nombre] = items_con_estado
    
    context = {
        'proyecto': proyecto,
        'plantilla': plantilla,
        'variables_globales_agrupadas': variables_globales_agrupadas,
        'variables_personalizadas_agrupadas': variables_personalizadas_agrupadas,
        'categorias': CampoMetanalisis.CATEGORIA_CHOICES,
        'tipos_dato': CampoMetanalisis.TIPO_DATO_CHOICES,
        'total_globales': variables_globales.count(),
        'total_personalizadas': variables_personalizadas.count(),
        'total_articulos': Articulo.objects.filter(proyecto=proyecto).count(),
        'campos_en_plantilla_ids': list(campos_en_plantilla.values_list('id', flat=True)),
    }
    
    return render(request, 'gestionar_variables_globales.html', context)

# === VISTAS DE EXPORTACIÓN EXCEL PARA META-ANÁLISIS ===
# ... (puedes pegar esto después de tu vista 'descargar_archivo_bib') ...

@login_required
def generar_excel_articulo(request, articulo_id):
    articulo = get_object_or_404(Articulo, id=articulo_id)
    
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=articulo.proyecto
    ).first()
    
    if not usuario_proyecto:
        messages.error(request, 'No tienes acceso a este artículo.')
        return redirect('mis_proyectos')

    asignaciones = AsignacionCampo.objects.filter(
        articulo=articulo,
        campo__categoria='EFECTOS'
    ).select_related('campo').order_by('campo__nombre')

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Datos de Efecto"

    headers = ["Artículo (Título)", "Bibtex Key", "Estado Artículo"]
    data_row = [articulo.titulo, articulo.bibtex_key, articulo.get_estado_display()]

    for asignacion in asignaciones:
        headers.append(asignacion.campo.nombre)
        
        try:
            valor_num = float(asignacion.valor)
            data_row.append(valor_num)
        except (ValueError, TypeError):
            data_row.append(asignacion.valor)

    ws.append(headers)
    ws.append(data_row)
    
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="004A99", end_color="004A99", fill_type="solid")
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for i, col in enumerate(ws.iter_cols(min_row=1, max_row=1, max_col=len(headers))):
        ws.column_dimensions[col[0].column_letter].autosize = True
    ws.column_dimensions['A'].width = 50

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    nombre_archivo = "".join(c for c in articulo.titulo if c.isalnum() or c in " ._").rstrip()[:50]
    response['Content-Disposition'] = f'attachment; filename="datos_efecto_{nombre_archivo}.xlsx"'
    
    wb.save(response)
    return response


@login_required
def generar_excel_proyecto(request, proyecto_id):

    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto,
        rol_proyecto__in=['SUPERVISOR', 'DUEÑO']
    ).first()
    
    if not usuario_proyecto:
        messages.error(request, 'No tienes permisos para generar este reporte.')
        return redirect('articulos:ver_articulos', proyecto_id=proyecto_id)

    try:
        plantilla = PlantillaBusqueda.objects.get(
            proyecto=proyecto, 
            es_predeterminada=True
        )
        campos_efectos = plantilla.campos.filter(categoria='EFECTOS').order_by('nombre')
    except PlantillaBusqueda.DoesNotExist:
        messages.error(request, 'Error: No se encontró la plantilla predeterminada del proyecto.')
        return redirect('articulos:ver_articulos', proyecto_id=proyecto_id)

    articulos = Articulo.objects.filter(proyecto=proyecto).order_by('titulo')
    # Obtener todas las asignaciones de efecto en una sola consulta para mejorar rendimiento
    from collections import defaultdict
    asignaciones_qs = AsignacionCampo.objects.filter(
        articulo__in=articulos,
        campo__in=campos_efectos
    ).select_related('campo', 'articulo')

    asign_map = defaultdict(dict)
    for a in asignaciones_qs:
        asign_map[a.articulo_id][a.campo_id] = a.valor

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Datos Generales de Efectos"

    headers = ["Artículo (Título)", "Bibtex Key", "Estado Artículo"]
    for campo in campos_efectos:
        headers.append(campo.nombre)
    ws.append(headers)
    
    # Estilo para los encabezados
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="004A99", end_color="004A99", fill_type="solid")
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill

    for articulo in articulos:
        fila = [
            articulo.titulo,
            articulo.bibtex_key,
            articulo.get_estado_display()
        ]
        
        for campo in campos_efectos:
            valor = asign_map.get(articulo.id, {}).get(campo.id)
            if valor is None:
                fila.append(None)
            else:
                try:
                    fila.append(float(valor))
                except (ValueError, TypeError):
                    fila.append(valor)
        
        ws.append(fila)

    ws.column_dimensions['A'].width = 50
    ws.column_dimensions['B'].width = 20
    ws.column_dimensions['C'].width = 15
    for i, col in enumerate(ws.iter_cols(min_col=4, max_col=len(headers))):
        ws.column_dimensions[col[0].column_letter].autosize = True

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    nombre_archivo = "".join(c for c in proyecto.nombre if c.isalnum() or c in " ._").rstrip()
    response['Content-Disposition'] = f'attachment; filename="datos_generales_{nombre_archivo}.xlsx"'
    
    wb.save(response)
    return response


@login_required
def seleccionar_descarga(request, proyecto_id):
    """Vista para seleccionar varios artículos y descargar sus Excel en un ZIP."""
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)

    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=proyecto
    ).first()

    if not usuario_proyecto:
        messages.error(request, 'No tienes acceso a este proyecto.')
        return redirect('mis_proyectos')

    if request.method == 'GET':
        q = request.GET.get('q', '').strip()
        estado = request.GET.get('estado', '')

        articulos_qs = Articulo.objects.filter(proyecto=proyecto).order_by('-fecha_carga')
        if q:
            articulos_qs = articulos_qs.filter(
                Q(titulo__icontains=q) |
                Q(bibtex_key__icontains=q) |
                Q(metadata_completos__icontains=q)
            )
        if estado:
            articulos_qs = articulos_qs.filter(estado=estado)

        context = {
            'proyecto': proyecto,
            'articulos': articulos_qs[:200],  # limitar para rendimiento
            'q': q,
            'estado': estado
        }
        return render(request, 'descargar_individual.html', context)

    # POST: generar ZIP con archivos xlsx por artículo seleccionado
    selected = request.POST.getlist('articulo_ids')
    if not selected:
        messages.error(request, 'No seleccionaste artículos para descargar.')
        return redirect('detalle_proyecto', proyecto_id=proyecto_id)

    articulos = Articulo.objects.filter(id__in=selected, proyecto=proyecto)
    if not articulos.exists():
        messages.error(request, 'No se encontraron los artículos solicitados.')
        return redirect('detalle_proyecto', proyecto_id=proyecto_id)

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as zf:
        for articulo in articulos:
            # Generar workbook (mismo formato que generar_excel_articulo)
            asignaciones = AsignacionCampo.objects.filter(
                articulo=articulo,
                campo__categoria='EFECTOS'
            ).select_related('campo').order_by('campo__nombre')

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Datos de Efecto"

            headers = ["Artículo (Título)", "Bibtex Key", "Estado Artículo"]
            data_row = [articulo.titulo, articulo.bibtex_key, articulo.get_estado_display()]

            for asignacion in asignaciones:
                headers.append(asignacion.campo.nombre)
                try:
                    valor_num = float(asignacion.valor)
                    data_row.append(valor_num)
                except (ValueError, TypeError):
                    data_row.append(asignacion.valor)

            ws.append(headers)
            ws.append(data_row)

            header_font = Font(bold=True, color="FFFFFF")
            header_fill = PatternFill(start_color="004A99", end_color="004A99", fill_type="solid")
            for cell in ws[1]:
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center")

            ws.column_dimensions['A'].width = 50

            excel_io = BytesIO()
            wb.save(excel_io)
            excel_io.seek(0)

            filename_safe = "".join(c for c in articulo.titulo if c.isalnum() or c in " ._").rstrip()[:40]
            zf.writestr(f"datos_efecto_{articulo.id}_{filename_safe}.xlsx", excel_io.getvalue())

    zip_buffer.seek(0)
    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    nombre_zip = "seleccion_articulos_{}.zip".format(proyecto.id)
    response['Content-Disposition'] = f'attachment; filename="{nombre_zip}"'
    return response


# ==================== PANEL DE CONTROL FOREST PLOT ====================

@login_required
def panel_forest_plot(request, proyecto_id):
    """
    Vista principal del panel de control para Forest Plot con filtros dinámicos
    """
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    usuario_proyecto = get_object_or_404(UsuarioProyecto, proyecto=proyecto, usuario=request.user)
    
    # Obtener la plantilla del proyecto
    try:
        plantilla = PlantillaBusqueda.objects.get(proyecto=proyecto)
        campos_plantilla_ids = plantilla.campos.values_list('id', flat=True)
    except PlantillaBusqueda.DoesNotExist:
        # Si no hay plantilla, usar lista vacía
        campos_plantilla_ids = []
    
    # Obtener solo campos numéricos que están en la plantilla (para calcular efecto)
    campos_numericos = CampoMetanalisis.objects.filter(
        id__in=campos_plantilla_ids,
        tipo_dato='NUMERO',
        activo=True
    ).order_by('nombre')
    
    # Obtener solo campos categóricos/descriptivos que están en la plantilla
    campos_categoricos = CampoMetanalisis.objects.filter(
        id__in=campos_plantilla_ids,
        tipo_dato__in=['TEXTO', 'OPCIONES', 'SI_NO'],
        activo=True
    ).order_by('categoria', 'nombre')
    
    # Obtener rango de años de publicación de los artículos (desde metadata_completos)
    articulos = Articulo.objects.filter(proyecto=proyecto)
    
    # Extraer años de los metadatos JSON
    años = []
    for articulo in articulos:
        if articulo.metadata_completos and 'year' in articulo.metadata_completos:
            try:
                año = int(articulo.metadata_completos['year'])
                años.append(año)
            except (ValueError, TypeError):
                pass
    
    año_minimo = min(años) if años else timezone.now().year
    año_maximo = max(años) if años else timezone.now().year
    
    # Contar artículos totales
    total_articulos = articulos.count()
    
    context = {
        'proyecto': proyecto,
        'usuario_proyecto': usuario_proyecto,
        'campos_numericos': campos_numericos,
        'campos_categoricos': campos_categoricos,
        'año_minimo': año_minimo,
        'año_maximo': año_maximo,
        'total_articulos': total_articulos,
    }
    
    return render(request, 'panel_forest_plot.html', context)


@login_required
def filtrar_forest_plot(request, proyecto_id):
    """
    Vista AJAX que filtra artículos y genera el Forest Plot
    Calcula automáticamente el tamaño de efecto desde los campos numéricos del proyecto
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)
    
    try:
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
        data = json.loads(request.body)
        
        # Obtener parámetros de filtro
        año_inicio = data.get('año_inicio')
        año_fin = data.get('año_fin')
        campo_categorico_codigo = data.get('campo_categorico')
        valor_categorico = data.get('valor_categorico')
        
        # Obtener campos numéricos de la plantilla del proyecto
        try:
            plantilla = PlantillaBusqueda.objects.get(proyecto=proyecto)
            campos_plantilla_ids = plantilla.campos.values_list('id', flat=True)
        except PlantillaBusqueda.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'No se encontró una plantilla de búsqueda para este proyecto'
            }, status=404)
        
        # Obtener campos numéricos
        campos_numericos = CampoMetanalisis.objects.filter(
            id__in=campos_plantilla_ids,
            tipo_dato='NUMERO',
            activo=True
        )
        
        if campos_numericos.count() < 2:
            return JsonResponse({
                'success': False,
                'error': 'Se requieren al menos 2 campos numéricos en la plantilla para calcular el tamaño de efecto'
            }, status=400)
        
        # Filtrar artículos
        articulos_query = Articulo.objects.filter(proyecto=proyecto)
        
        # Filtro por año de publicación (desde metadata_completos)
        if año_inicio or año_fin:
            articulos_filtrados_ids = []
            for articulo in articulos_query:
                if articulo.metadata_completos and 'year' in articulo.metadata_completos:
                    try:
                        año = int(articulo.metadata_completos['year'])
                        cumple_filtro = True
                        if año_inicio and año < int(año_inicio):
                            cumple_filtro = False
                        if año_fin and año > int(año_fin):
                            cumple_filtro = False
                        if cumple_filtro:
                            articulos_filtrados_ids.append(articulo.id)
                    except (ValueError, TypeError):
                        pass
            articulos_query = articulos_query.filter(id__in=articulos_filtrados_ids)
        
        # Filtro por variable categórica/descriptiva
        if campo_categorico_codigo and valor_categorico:
            campo_cat = get_object_or_404(CampoMetanalisis, codigo=campo_categorico_codigo)
            articulos_con_valor = AsignacionCampo.objects.filter(
                campo=campo_cat,
                valor__icontains=valor_categorico
            ).values_list('articulo_id', flat=True)
            articulos_query = articulos_query.filter(id__in=articulos_con_valor)
        
        # Verificar que hay artículos
        if not articulos_query.exists():
            return JsonResponse({
                'success': True,
                'total_articulos': 0,
                'articulos_con_datos': 0,
                'plot_data': None,
                'efecto_promedio': None,
                'error_promedio': None,
                'mensaje': 'No se encontraron artículos con los filtros aplicados'
            })
        
        # Importar pandas y plotly
        try:
            import pandas as pd
            import plotly.graph_objects as go
            import plotly.io as pio
            import numpy as np
        except ImportError:
            return JsonResponse({
                'success': False,
                'error': 'Las librerías pandas y plotly no están instaladas. Ejecuta: pip install pandas plotly'
            }, status=500)
        
        # Construir DataFrame con todos los campos numéricos
        datos_articulos = []
        for articulo in articulos_query:
            asignaciones = AsignacionCampo.objects.filter(
                articulo=articulo,
                campo__in=campos_numericos
            ).values('campo__codigo', 'campo__nombre', 'valor')
            
            valores = {asig['campo__codigo']: asig['valor'] for asig in asignaciones}
            if len(valores) >= 2:  # Al menos 2 campos numéricos
                valores['articulo_titulo'] = articulo.titulo
                valores['articulo_id'] = articulo.id
                # Extraer año si está disponible
                if articulo.metadata_completos and 'year' in articulo.metadata_completos:
                    valores['año'] = articulo.metadata_completos['year']
                datos_articulos.append(valores)
        
        if not datos_articulos:
            return JsonResponse({
                'success': True,
                'total_articulos': articulos_query.count(),
                'articulos_con_datos': 0,
                'plot_data': None,
                'efecto_promedio': None,
                'error_promedio': None,
                'mensaje': 'Los artículos filtrados no tienen suficientes datos numéricos'
            })
        
        df = pd.DataFrame(datos_articulos)
        
        # Convertir todos los campos numéricos
        campos_codigo = [c.codigo for c in campos_numericos]
        for codigo in campos_codigo:
            if codigo in df.columns:
                df[codigo] = pd.to_numeric(df[codigo], errors='coerce')
        
        # Calcular tamaño de efecto automáticamente desde TODAS las variables numéricas
        # Para cada artículo, combinar todas sus variables numéricas en un solo efecto
        columnas_numericas = [col for col in df.columns if col in campos_codigo and df[col].notna().sum() > 0]
        
        if len(columnas_numericas) < 1:
            return JsonResponse({
                'success': True,
                'total_articulos': articulos_query.count(),
                'articulos_con_datos': 0,
                'plot_data': None,
                'efecto_promedio': None,
                'error_promedio': None,
                'mensaje': 'No hay campos numéricos con datos válidos'
            })
        
        # Calcular el efecto promedio de todas las variables numéricas para cada artículo
        df['efecto'] = df[columnas_numericas].mean(axis=1)
        df['error'] = df[columnas_numericas].std(axis=1) / np.sqrt(len(columnas_numericas))
        
        # Filtrar artículos con datos válidos
        df = df[['articulo_titulo', 'articulo_id', 'efecto', 'error']].dropna()
        
        campo_efecto_nombre = "Efecto Promedio (todas las variables)"
        campo_error_nombre = "Error Estándar"
        
        if len(df) == 0:
            return JsonResponse({
                'success': True,
                'total_articulos': articulos_query.count(),
                'articulos_con_datos': 0,
                'plot_data': None,
                'efecto_promedio': None,
                'error_promedio': None,
                'mensaje': 'Los artículos no tienen valores numéricos válidos en los campos seleccionados'
            })
        
        # Calcular intervalos de confianza
        df['ci_lower'] = df['efecto'] - 1.96 * df['error']
        df['ci_upper'] = df['efecto'] + 1.96 * df['error']
        
        # Calcular peso y promedios con validación
        df['peso'] = 1 / (df['error']**2)
        
        # Validar que hay pesos válidos antes de calcular promedio
        suma_pesos = df['peso'].sum()
        if suma_pesos == 0 or np.isnan(suma_pesos) or np.isinf(suma_pesos):
            efecto_promedio = 0
            error_promedio = 0
            ci_lower_promedio = 0
            ci_upper_promedio = 0
        else:
            efecto_promedio = (df['efecto'] * df['peso']).sum() / suma_pesos
            error_promedio = (1 / suma_pesos)**0.5
            ci_lower_promedio = efecto_promedio - 1.96 * error_promedio
            ci_upper_promedio = efecto_promedio + 1.96 * error_promedio
        
        # Crear Forest Plot con diseño mejorado
        fig = go.Figure()
        
        # Añadir estudios individuales (variables numéricas)
        fig.add_trace(go.Scatter(
            x=df['efecto'],
            y=df['articulo_titulo'],
            mode='markers',
            marker=dict(
                color='black',
                size=8,
                symbol='circle'
            ),
            name='Artículos',
            error_x=dict(
                type='data',
                array=df['ci_upper'] - df['efecto'],
                arrayminus=df['efecto'] - df['ci_lower'],
                visible=True,
                color='#EF4444',
                thickness=2,
                width=0
            ),
            hoverinfo='skip'
        ))
        
        # Añadir promedio ponderado
        fig.add_trace(go.Scatter(
            x=[efecto_promedio],
            y=['<b>⬥ EFECTO COMBINADO</b>'],
            mode='markers',
            marker=dict(
                color='#DC2626',
                size=16,
                symbol='diamond',
                line=dict(width=2, color='#7F1D1D')
            ),
            name='Efecto Combinado',
            error_x=dict(
                type='data',
                array=[ci_upper_promedio - efecto_promedio],
                arrayminus=[efecto_promedio - ci_lower_promedio],
                visible=True,
                color='#DC2626',
                thickness=4,
                width=0
            ),
            hoverinfo='skip'
        ))
        
        # Línea de no efecto
        linea_nula = 0
        fig.add_vline(
            x=linea_nula, 
            line_width=2, 
            line_dash="dash", 
            line_color="#9CA3AF"
        )
        
        # Configurar layout mejorado
        fig.update_layout(
            title=dict(
                text=f'<b>Forest Plot</b><br><sub>Efecto promedio de {len(columnas_numericas)} variables numéricas (n={len(df)} artículos)</sub>',
                font=dict(size=22, color='#111827', family='Arial, sans-serif'),
                x=0.5,
                xanchor='center'
            ),
            xaxis=dict(
                title=dict(
                    text=f'<b>{campo_efecto_nombre}</b>',
                    font=dict(size=14, color='#374151')
                ),
                showgrid=True,
                gridwidth=1,
                gridcolor='#E5E7EB',
                zeroline=True,
                zerolinewidth=2,
                zerolinecolor='#9CA3AF',
                showline=True,
                linewidth=2,
                linecolor='#D1D5DB',
                tickfont=dict(size=11, color='#4B5563')
            ),
            yaxis=dict(
                title=dict(
                    text='<b>Artículos</b>',
                    font=dict(size=14, color='#374151')
                ),
                autorange="reversed",
                showgrid=False,
                showline=True,
                linewidth=2,
                linecolor='#D1D5DB',
                tickfont=dict(size=10, color='#1F2937')
            ),
            hovermode="closest",
            plot_bgcolor='#F9FAFB',
            paper_bgcolor='white',
            autosize=True,
            margin=dict(l=250, r=60, t=100, b=70),
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=-0.15,
                xanchor="center",
                x=0.5,
                bgcolor='rgba(255,255,255,0.9)',
                bordercolor='#D1D5DB',
                borderwidth=1,
                font=dict(size=11, color='#374151')
            ),
            font=dict(family='Arial, sans-serif')
        )
        
        # Convertir a JSON
        plot_json = json.loads(pio.to_json(fig))
        
        return JsonResponse({
            'success': True,
            'total_articulos': articulos_query.count(),
            'articulos_con_datos': len(df),
            'plot_data': plot_json,
            'efecto_promedio': round(efecto_promedio, 4),
            'error_promedio': round(error_promedio, 4),
            'intervalo_confianza_inferior': round(efecto_promedio - 1.96 * error_promedio, 4),
            'intervalo_confianza_superior': round(efecto_promedio + 1.96 * error_promedio, 4)
        })
        
    except CampoMetanalisis.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Campo no encontrado'}, status=404)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'Error: {str(e)}'}, status=500)


# ... (otras importaciones) ...
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio


@login_required
def generar_forest_plot(request, proyecto_id):
    """
    Genera datos de un Forest Plot para un grupo de artículos
    y los devuelve como JSON para Plotly.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    try:
        # 1. Obtener parámetros del POST
        data = json.loads(request.body)
        archivo_bib = data.get('archivo_bib')
        usuario_id = data.get('usuario_id')
        effect_code = data.get('effect_size_code')
        error_code = data.get('standard_error_code')

        if not all([archivo_bib, effect_code, error_code, proyecto_id]):
            return JsonResponse({'success': False, 'error': 'Faltan parámetros (archivo_bib, effect_code, error_code, proyecto_id)'}, status=400)

        # 2. Obtener los artículos base
        base_query = Articulo.objects.filter(
            proyecto_id=proyecto_id,
            archivo_bib=archivo_bib
        )
        
        # Si se pasó un usuario_id (vista de DUEÑO), filtrar por ese usuario
        if usuario_id:
            try:
                # Intenta convertir a entero, ya que viene de JS
                user_id_int = int(usuario_id)
                base_query = base_query.filter(usuario_carga_id=user_id_int)
            except (ValueError, TypeError):
                pass # Ignorar si el ID no es válido
        
        # 3. Obtener los campos de 'Tamaño de Efecto' y 'Error'
        
        # Obtener los IDs de los campos
        campo_efecto_id = get_object_or_404(CampoMetanalisis, codigo=effect_code).id
        campo_error_id = get_object_or_404(CampoMetanalisis, codigo=error_code).id
        
        # Obtener los artículos que SÍ tienen estos campos
        articulos_con_datos = base_query.filter(
            campos_asignados__campo_id__in=[campo_efecto_id, campo_error_id]
        ).distinct()

        if not articulos_con_datos.exists():
            return JsonResponse({'success': False, 'error': f'No se encontraron artículos en este grupo con los campos "{effect_code}" y "{error_code}".'}, status=404)

        # 4. Construir el DataFrame con Pandas
        data_efecto = list(AsignacionCampo.objects.filter(
            articulo__in=articulos_con_datos,
            campo_id=campo_efecto_id
        ).values('articulo__titulo', 'valor'))

        data_error = list(AsignacionCampo.objects.filter(
            articulo__in=articulos_con_datos,
            campo_id=campo_error_id
        ).values('articulo__titulo', 'valor'))

        # Convertir a DataFrames
        df_efecto = pd.DataFrame(data_efecto).rename(columns={'valor': 'efecto', 'articulo__titulo': 'articulo'})
        df_error = pd.DataFrame(data_error).rename(columns={'valor': 'error', 'articulo__titulo': 'articulo'})

        # Unir los dataframes
        df = pd.merge(df_efecto, df_error, on='articulo')

        # Convertir valores a numérico (importante)
        df['efecto'] = pd.to_numeric(df['efecto'], errors='coerce')
        df['error'] = pd.to_numeric(df['error'], errors='coerce')
        df = df.dropna() # Eliminar filas donde la conversión falló

        if df.empty:
            return JsonResponse({'success': False, 'error': 'Los datos encontrados no son numéricos. Revisa los valores guardados.'}, status=400)
        
        # Calcular el promedio y los intervalos de confianza (simplificado)
        # Nota: Un meta-análisis real usaría 'pesos' (weights = 1 / (error^2))
        df['peso'] = 1 / (df['error']**2)
        efecto_promedio = (df['efecto'] * df['peso']).sum() / df['peso'].sum()
        error_promedio = (1 / df['peso'].sum())**0.5
        
        # 5. Crear el Gráfico Forest Plot con Plotly
        fig = go.Figure()

        # Añadir los estudios individuales (puntos)
        fig.add_trace(go.Scatter(
            x=df['efecto'],
            y=df['articulo'],
            mode='markers',
            marker=dict(color='blue', size=8),
            name='Efecto del Estudio',
            error_x=dict(
                type='data',
                array=df['error'] * 1.96, # Asumiendo 95% CI (z=1.96)
                visible=True
            ),
            text=[f"Efecto: {row.efecto:.2f} (Error: {row.error:.2f})" for index, row in df.iterrows()],
            hoverinfo='text+y'
        ))

        # Añadir la línea de efecto promedio (diamante)
        fig.add_trace(go.Scatter(
            x=[efecto_promedio],
            y=['<b>Promedio General</b>'],
            mode='markers',
            marker=dict(color='red', size=16, symbol='diamond'),
            name='Promedio Ponderado',
            error_x=dict(
                type='data',
                array=[error_promedio * 1.96],
                visible=True
            ),
            text=f"Promedio: {efecto_promedio:.2f} (Error: {error_promedio:.2f})",
            hoverinfo='text'
        ))

        # Añadir la línea de "no efecto" (generalmente en 0 o 1)
        linea_nula = 0 # Para correlaciones/diferencias
        if 'ratio' in effect_code:
            linea_nula = 1 # Para Odds Ratio o Risk Ratio
            
        fig.add_vline(x=linea_nula, line_width=1, line_dash="dash", line_color="black")

        # Configurar el layout
        fig.update_layout(
            title=f'Forest Plot para "{effect_code}"',
            xaxis_title=f"Tamaño de Efecto ({effect_code})",
            yaxis_title="Estudio",
            yaxis=dict(autorange="reversed"), # Poner el promedio al final
            hovermode="closest",
            template="plotly_white",
            margin=dict(l=100, r=40, t=60, b=40)
        )

        # 6. Convertir gráfico a JSON
        plot_json = json.loads(pio.to_json(fig))

        return JsonResponse({
            'success': True,
            'plot_data': plot_json,
            'efecto_promedio': efecto_promedio,
            'error_promedio': error_promedio
        })

    except CampoMetanalisis.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Uno de los códigos de campo (effect o error) no existe.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Error interno del servidor: {str(e)}'}, status=500)


# ==================== ANÁLISIS DE COMPONENTES PRINCIPALES (PCA) ====================

@login_required
def panel_pca(request, proyecto_id):
    """Panel de control para Análisis de Componentes Principales"""
    proyecto = get_object_or_404(Proyecto, id=proyecto_id)
    
    # Verificar permisos
    es_miembro = UsuarioProyecto.objects.filter(
        proyecto=proyecto,
        usuario=request.user
    ).exists()
    
    if not (proyecto.usuario_creador == request.user or es_miembro):
        messages.error(request, 'No tienes permisos para acceder a este proyecto')
        return redirect('mis_proyectos')
    
    # Obtener plantilla del proyecto
    try:
        plantilla = PlantillaBusqueda.objects.get(proyecto=proyecto)
    except PlantillaBusqueda.DoesNotExist:
        messages.error(request, 'Este proyecto no tiene una plantilla configurada')
        return redirect('detalle_proyecto', proyecto_id=proyecto.id)
    
    # Obtener campos numéricos y categóricos
    campos_numericos = CampoMetanalisis.objects.filter(
        plantillas=plantilla,
        tipo_dato='NUMERO'
    ).order_by('nombre')
    
    campos_categoricos = CampoMetanalisis.objects.filter(
        plantillas=plantilla,
        tipo_dato__in=['TEXTO', 'OPCIONES']
    ).order_by('nombre')
    
    # Validar que haya suficientes campos numéricos para PCA
    if campos_numericos.count() < 2:
        messages.warning(request, 'Se necesitan al menos 2 campos numéricos para realizar el análisis PCA')
        return redirect('detalle_proyecto', proyecto_id=proyecto.id)
    
    # Obtener artículos del proyecto
    articulos = Articulo.objects.filter(proyecto=proyecto)
    total_articulos = articulos.count()
    
    # Calcular rango de años disponibles
    años = []
    for articulo in articulos:
        if articulo.metadata_completos and 'year' in articulo.metadata_completos:
            try:
                años.append(int(articulo.metadata_completos['year']))
            except (ValueError, TypeError):
                pass
    
    año_minimo = min(años) if años else 2000
    año_maximo = max(años) if años else 2024
    
    context = {
        'proyecto': proyecto,
        'plantilla': plantilla,
        'campos_numericos': campos_numericos,
        'campos_categoricos': campos_categoricos,
        'total_articulos': total_articulos,
        'año_minimo': año_minimo,
        'año_maximo': año_maximo,
    }
    
    return render(request, 'panel_pca.html', context)


@login_required
def filtrar_pca(request, proyecto_id):
    """API para filtrar artículos y generar gráficos PCA"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)
    
    try:
        proyecto = get_object_or_404(Proyecto, id=proyecto_id)
        
        # Verificar permisos
        es_miembro = UsuarioProyecto.objects.filter(
            proyecto=proyecto,
            usuario=request.user
        ).exists()
        
        if not (proyecto.usuario_creador == request.user or es_miembro):
            return JsonResponse({'success': False, 'error': 'No tienes permisos'}, status=403)
        
        # Parsear datos del request
        data = json.loads(request.body)
        año_inicio = data.get('año_inicio')
        año_fin = data.get('año_fin')
        
        # Obtener plantilla y campos
        plantilla = PlantillaBusqueda.objects.get(proyecto=proyecto)
        campos_numericos = CampoMetanalisis.objects.filter(
            plantillas=plantilla,
            tipo_dato='NUMERO'
        )
        
        if campos_numericos.count() < 2:
            return JsonResponse({
                'success': False,
                'error': 'Se necesitan al menos 2 campos numéricos para PCA'
            })
        
        # Filtrar artículos
        articulos_query = Articulo.objects.filter(proyecto=proyecto)
        
        # Filtro por año de publicación
        if año_inicio or año_fin:
            articulos_filtrados_ids = []
            for articulo in articulos_query:
                if articulo.metadata_completos and 'year' in articulo.metadata_completos:
                    try:
                        año = int(articulo.metadata_completos['year'])
                        cumple_filtro = True
                        if año_inicio and año < int(año_inicio):
                            cumple_filtro = False
                        if año_fin and año > int(año_fin):
                            cumple_filtro = False
                        if cumple_filtro:
                            articulos_filtrados_ids.append(articulo.id)
                    except (ValueError, TypeError):
                        pass
            articulos_query = articulos_query.filter(id__in=articulos_filtrados_ids)
        
        if not articulos_query.exists():
            return JsonResponse({
                'success': True,
                'total_articulos': 0,
                'articulos_con_datos': 0,
                'plots': None,
                'mensaje': 'No se encontraron artículos con los filtros aplicados'
            })
        
        # Construir DataFrame con datos numéricos (optimizado)
        datos_articulos = []
        
        # Obtener todas las asignaciones de una sola consulta
        asignaciones_query = AsignacionCampo.objects.filter(
            articulo__in=articulos_query,
            campo__in=campos_numericos
        ).select_related('articulo', 'campo').values(
            'articulo_id', 'articulo__titulo', 'campo__codigo', 'valor'
        )
        
        # Agrupar asignaciones por artículo
        articulos_dict = {}
        for asig in asignaciones_query:
            articulo_id = asig['articulo_id']
            if articulo_id not in articulos_dict:
                articulos_dict[articulo_id] = {
                    'articulo_titulo': asig['articulo__titulo'],
                    'articulo_id': articulo_id
                }
            articulos_dict[articulo_id][asig['campo__codigo']] = asig['valor']
        
        # Filtrar artículos con al menos 2 valores
        for articulo_id, valores in articulos_dict.items():
            # Contar solo valores de campos numéricos (excluir articulo_titulo y articulo_id)
            num_valores = sum(1 for k in valores.keys() if k not in ['articulo_titulo', 'articulo_id'])
            if num_valores >= 2:
                datos_articulos.append(valores)
        
        if not datos_articulos:
            return JsonResponse({
                'success': True,
                'total_articulos': articulos_query.count(),
                'articulos_con_datos': 0,
                'plots': None,
                'mensaje': 'Los artículos filtrados no tienen suficientes datos numéricos'
            })
        
        df = pd.DataFrame(datos_articulos)
        
        # Convertir campos numéricos
        campos_codigo = [c.codigo for c in campos_numericos]
        for codigo in campos_codigo:
            if codigo in df.columns:
                df[codigo] = pd.to_numeric(df[codigo], errors='coerce')
        
        # Seleccionar solo columnas numéricas válidas
        columnas_numericas = [col for col in df.columns if col in campos_codigo and df[col].notna().sum() > 0]
        
        if len(columnas_numericas) < 2:
            return JsonResponse({
                'success': True,
                'total_articulos': articulos_query.count(),
                'articulos_con_datos': 0,
                'plots': None,
                'mensaje': 'No hay suficientes campos numéricos con datos válidos (mínimo 2)'
            })
        
        # Filtrar artículos con datos completos
        df_numeric = df[columnas_numericas + ['articulo_titulo']].dropna()
        
        if len(df_numeric) < 2:
            return JsonResponse({
                'success': True,
                'total_articulos': articulos_query.count(),
                'articulos_con_datos': len(df_numeric),
                'plots': None,
                'mensaje': 'No hay suficientes artículos con datos completos (mínimo 2)'
            })
        
        # Preparar datos para PCA
        X = df_numeric[columnas_numericas].values
        articulos_nombres = df_numeric['articulo_titulo'].values
        
        # Estandarizar datos
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        # Aplicar PCA
        n_components = min(len(columnas_numericas), len(df_numeric))
        
        # Validación: se necesitan al menos 2 componentes para PCA
        if n_components < 2:
            return JsonResponse({
                'success': True,
                'total_articulos': articulos_query.count(),
                'articulos_con_datos': len(df_numeric),
                'plots': None,
                'mensaje': f'Se necesitan al menos 2 componentes principales para PCA (tienes {n_components}). Asegúrate de tener mínimo 2 campos numéricos con datos completos'
            })
        
        pca = PCA(n_components=n_components)
        X_pca = pca.fit_transform(X_scaled)
        
        # Obtener nombres de variables
        campos_dict = {campo.codigo: campo.nombre for campo in campos_numericos}
        nombres_variables = [campos_dict.get(col, col) for col in columnas_numericas]
        
        # ===== GRÁFICO 1: SCREE PLOT (Varianza Explicada) =====
        varianza_explicada = pca.explained_variance_ratio_ * 100
        varianza_acumulada = np.cumsum(varianza_explicada)
        
        scree_trace1 = go.Bar(
            x=[f'PC{i+1}' for i in range(n_components)],
            y=varianza_explicada,
            name='Varianza Explicada',
            marker_color='#3B82F6',
            text=[f'{v:.1f}%' for v in varianza_explicada],
            textposition='auto'
        )
        
        scree_trace2 = go.Scatter(
            x=[f'PC{i+1}' for i in range(n_components)],
            y=varianza_acumulada,
            name='Varianza Acumulada',
            mode='lines+markers',
            marker=dict(color='#EF4444', size=8),
            line=dict(color='#EF4444', width=2),
            yaxis='y2',
            text=[f'{v:.1f}%' for v in varianza_acumulada],
            hovertemplate='%{text}<extra></extra>'
        )
        
        scree_layout = go.Layout(
            title=dict(
                text='<b>Scree Plot - Varianza Explicada por Componente</b>',
                font=dict(size=18, color='#111827')
            ),
            xaxis=dict(
                title='<b>Componentes Principales</b>',
                showgrid=True,
                gridcolor='#E5E7EB'
            ),
            yaxis=dict(
                title='<b>Varianza Explicada (%)</b>',
                range=[0, max(varianza_explicada) * 1.2],
                showgrid=True,
                gridcolor='#E5E7EB',
                side='left'
            ),
            yaxis2=dict(
                title='<b>Varianza Acumulada (%)</b>',
                range=[0, 105],
                overlaying='y',
                side='right',
                showgrid=False
            ),
            hovermode='x unified',
            plot_bgcolor='#F9FAFB',
            paper_bgcolor='white',
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
        
        scree_plot = {
            'data': [scree_trace1, scree_trace2],
            'layout': scree_layout
        }
        
        # ===== GRÁFICO 2: BIPLOT (Dimensiones 1 y 2) =====
        if n_components >= 2:
            # Obtener títulos de artículos
            titulos_articulos = df_numeric['articulo_titulo'].values
            
            # Preparar traces para VECTORES de variables con flechas
            biplot_traces_arrows = []
            loadings = pca.components_[:2, :].T  # Variables x Componentes
            
            # Escalar vectores para que sean visibles junto a los artículos
            max_articulo = max(abs(X_pca[:, 0]).max(), abs(X_pca[:, 1]).max())
            max_loading = max(abs(loadings[:, 0]).max(), abs(loadings[:, 1]).max())
            scale_factor = (max_articulo / max_loading) * 0.8 if max_loading > 0 else 1
            
            # Preparar annotations para flechas de variables
            biplot_annotations = []
            
            for i, var_name in enumerate(nombres_variables):
                x_end = loadings[i, 0] * scale_factor
                y_end = loadings[i, 1] * scale_factor
                
                # Posicionar texto con offset (1.15x como en matplotlib)
                x_text = x_end * 1.15
                y_text = y_end * 1.15
                
                # Flecha desde origen hasta la punta
                biplot_annotations.append(dict(
                    ax=0, ay=0,  # Punto de inicio (origen)
                    x=x_end, y=y_end,  # Punto final
                    xref='x', yref='y',
                    axref='x', ayref='y',
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1.5,
                    arrowwidth=2.5,
                    arrowcolor='#DC2626',
                    text='',  # Sin texto en la flecha
                    hovertext=var_name
                ))
                
                # Texto separado con offset
                biplot_annotations.append(dict(
                    x=x_text, y=y_text,
                    xref='x', yref='y',
                    text=var_name,
                    showarrow=False,
                    font=dict(size=11, color='#DC2626', family='Arial, sans-serif'),
                    xanchor='center',
                    yanchor='middle'
                ))
            
            # PUNTOS de artículos
            biplot_trace_points = go.Scatter(
                x=X_pca[:, 0],
                y=X_pca[:, 1],
                mode='markers+text',
                marker=dict(
                    color='#3B82F6',
                    size=10,
                    symbol='circle',
                    line=dict(width=1.5, color='white')
                ),
                text=[f'A{i+1}' for i in range(len(titulos_articulos))],
                textposition='top center',
                textfont=dict(
                    size=9,
                    color='#1E3A8A',
                    family='Arial, sans-serif'
                ),
                name='Artículos',
                hoverinfo='skip'
            )
            
            biplot_layout = go.Layout(
                title=dict(
                    text=f'<b>Biplot PCA</b><br><sub>PC1: {varianza_explicada[0]:.1f}% | PC2: {varianza_explicada[1]:.1f}%</sub>',
                    font=dict(size=18, color='#111827'),
                    x=0.5,
                    xanchor='center'
                ),
                xaxis=dict(
                    title=f'<b>PC1 ({varianza_explicada[0]:.1f}%)</b>',
                    showgrid=True,
                    gridcolor='#E5E7EB',
                    zeroline=True,
                    zerolinecolor='#9CA3AF',
                    zerolinewidth=2
                ),
                yaxis=dict(
                    title=f'<b>PC2 ({varianza_explicada[1]:.1f}%)</b>',
                    showgrid=True,
                    gridcolor='#E5E7EB',
                    zeroline=True,
                    zerolinecolor='#9CA3AF',
                    zerolinewidth=2
                ),
                annotations=biplot_annotations,
                hovermode='closest',
                plot_bgcolor='#F9FAFB',
                paper_bgcolor='white',
                showlegend=True,
                legend=dict(
                    orientation="v",
                    yanchor="middle",
                    y=0.5,
                    xanchor="left",
                    x=1.02
                )
            )
            
            biplot = {
                'data': [biplot_trace_points],
                'layout': biplot_layout
            }
            
            # Guardar coordenadas del Biplot para exportación
            request.session[f'pca_biplot_{proyecto_id}'] = {
                'articulos': [
                    {
                        'articulo_titulo': titulos_articulos[i],
                        'X': float(X_pca[i, 0]),
                        'Y': float(X_pca[i, 1])
                    }
                    for i in range(len(titulos_articulos))
                ]
            }
        else:
            biplot = None
        
        # ===== GRÁFICO 3: COS2 (Calidad de Representación) =====
        # Calcular cos2 para artículos en todos los componentes
        if n_components >= 2:
            # Cos2 de artículos = coordenadas al cuadrado / distancia al origen
            titulos_articulos = df_numeric['articulo_titulo'].values
            
            # Distancia al origen en el espacio PCA completo
            dist_sq = np.sum(X_pca**2, axis=1)
            
            # COS² para cada artículo y componente
            cos2_articulos = (X_pca**2) / dist_sq[:, np.newaxis]
            
            # Etiquetas
            etiquetas_articulos = [f'A{i+1}' for i in range(len(titulos_articulos))]
            etiquetas_dims = [f'PC{i+1}' for i in range(n_components)]
            
            # Crear heatmap estilo corrplot (cuadrados en lugar de círculos)
            cos2_trace = go.Heatmap(
                z=cos2_articulos,
                x=etiquetas_dims,
                y=etiquetas_articulos,
                colorscale='RdYlBu_r',  # Similar a coolwarm de seaborn
                zmid=0.5,
                text=[[f'{val:.2f}' for val in row] for row in cos2_articulos],
                texttemplate='%{text}',
                textfont=dict(size=10),
                colorbar=dict(
                    title=dict(text='COS²', side='right'),
                    tickmode='linear',
                    tick0=0,
                    dtick=0.2
                ),
                hoverinfo='skip'
            )
            
            cos2_traces = [cos2_trace]
            
            cos2_layout = go.Layout(
                title=dict(
                    text='<b>Calidad de Representación (COS² - CORRPLOT)</b>',
                    font=dict(size=18, color='#111827'),
                    x=0.5,
                    xanchor='center'
                ),
                xaxis=dict(
                    title='<b>Componentes Principales</b>',
                    side='bottom',
                    showgrid=False
                ),
                yaxis=dict(
                    title='<b>Artículos</b>',
                    autorange='reversed',  # A1 arriba
                    showgrid=False
                ),
                plot_bgcolor='white',
                paper_bgcolor='white',
                height=max(400, len(etiquetas_articulos) * 40)
            )
            
            cos2_plot = {
                'data': cos2_traces,
                'layout': cos2_layout
            }
        else:
            cos2_plot = None
        
        # ===== GRÁFICO 4: CÍRCULO DE CORRELACIÓN =====
        if n_components >= 2:
            # Crear círculo unitario de referencia
            theta = np.linspace(0, 2*np.pi, 100)
            circle_x = np.cos(theta)
            circle_y = np.sin(theta)
            
            correlation_traces = [
                # Círculo unitario
                go.Scatter(
                    x=circle_x,
                    y=circle_y,
                    mode='lines',
                    line=dict(color='#D1D5DB', width=2, dash='dash'),
                    name='Círculo Unitario',
                    showlegend=False,
                    hoverinfo='skip'
                )
            ]
            
            # Agregar vectores de variables (correlaciones)
            loadings = pca.components_[:2, :].T  # Variables x Componentes
            
            # Preparar annotations para flechas de variables
            correlation_annotations = []
            
            for i, var_name in enumerate(nombres_variables):
                x_end = loadings[i, 0]
                y_end = loadings[i, 1]
                
                # Posicionar texto con offset (1.15x como en matplotlib)
                x_text = x_end * 1.15
                y_text = y_end * 1.15
                
                # Flecha desde origen hasta la punta
                correlation_annotations.append(dict(
                    ax=0, ay=0,  # Punto de inicio (origen)
                    x=x_end, y=y_end,  # Punto final
                    xref='x', yref='y',
                    axref='x', ayref='y',
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1.5,
                    arrowwidth=2.5,
                    arrowcolor='#DC2626',
                    text='',  # Sin texto en la flecha
                    hovertext=var_name
                ))
                
                # Texto separado con offset
                correlation_annotations.append(dict(
                    x=x_text, y=y_text,
                    xref='x', yref='y',
                    text=var_name,
                    showarrow=False,
                    font=dict(size=11, color='#DC2626', family='Arial, sans-serif'),
                    xanchor='center',
                    yanchor='middle'
                ))
            
            correlation_layout = go.Layout(
                title=dict(
                    text='<b>Círculo de Correlación</b>',
                    font=dict(size=18, color='#111827')
                ),
                xaxis=dict(
                    title=f'<b>PC1 ({varianza_explicada[0]:.1f}%)</b>',
                    range=[-1.1, 1.1],
                    showgrid=True,
                    gridcolor='#E5E7EB',
                    zeroline=True,
                    zerolinecolor='#9CA3AF',
                    zerolinewidth=2
                ),
                yaxis=dict(
                    title=f'<b>PC2 ({varianza_explicada[1]:.1f}%)</b>',
                    range=[-1.1, 1.1],
                    showgrid=True,
                    gridcolor='#E5E7EB',
                    zeroline=True,
                    zerolinecolor='#9CA3AF',
                    zerolinewidth=2,
                    scaleanchor='x',
                    scaleratio=1
                ),
                annotations=correlation_annotations,
                hovermode='closest',
                plot_bgcolor='#F9FAFB',
                paper_bgcolor='white'
            )
            
            correlation_circle = {
                'data': correlation_traces,
                'layout': correlation_layout
            }
        else:
            correlation_circle = None
        
        # ===== GRÁFICO 5: ANÁLISIS DE CLUSTERS (K-MEANS) =====
        cluster_plot = None
        if n_components >= 2 and len(df_numeric) >= 3:
            # Se necesitan al menos 3 muestras para hacer un análisis de clusters significativo
            from sklearn.cluster import KMeans
            
            # Número de clusters: máximo 3, pero limitado por número de artículos
            n_clusters = min(3, len(df_numeric))
            
            # Aplicar K-Means sobre los componentes principales
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            clusters = kmeans.fit_predict(X_pca[:, :2])  # Usar solo PC1 y PC2
            
            # Añadir clusters al DataFrame
            df_numeric['Cluster'] = clusters + 1  # Clusters 1, 2, 3...
            
            # Colores para cada cluster (tomar solo los necesarios)
            colores_disponibles = ['#3B82F6', '#EF4444', '#10B981']  # Azul, Rojo, Verde
            colores_clusters = colores_disponibles[:n_clusters]
            
            # Crear traces para cada cluster
            cluster_traces = []
            for i in range(n_clusters):
                mask = clusters == i
                cluster_traces.append(go.Scatter(
                    x=X_pca[mask, 0],
                    y=X_pca[mask, 1],
                    mode='markers+text',
                    marker=dict(
                        color=colores_clusters[i],
                        size=12,
                        symbol='circle',
                        line=dict(width=2, color='white')
                    ),
                    text=[f'A{j+1}' for j in range(len(titulos_articulos)) if clusters[j] == i],
                    textposition='top center',
                    textfont=dict(size=9, color='#111827', family='Arial, sans-serif'),
                    name=f'Cluster {i+1}',
                    hoverinfo='skip'
                ))
            
            # Añadir centroides
            centroides = kmeans.cluster_centers_
            cluster_traces.append(go.Scatter(
                x=centroides[:, 0],
                y=centroides[:, 1],
                mode='markers',
                marker=dict(
                    color='black',
                    size=15,
                    symbol='x',
                    line=dict(width=2, color='white')
                ),
                name='Centroides',
                showlegend=True,
                hoverinfo='skip'
            ))
            
            cluster_layout = go.Layout(
                title=dict(
                    text=f'<b>Análisis de Clusters (K-Means, k={n_clusters})</b>',
                    font=dict(size=18, color='#111827'),
                    x=0.5,
                    xanchor='center'
                ),
                xaxis=dict(
                    title=f'<b>PC1 ({varianza_explicada[0]:.1f}%)</b>',
                    showgrid=True,
                    gridcolor='#E5E7EB',
                    zeroline=True,
                    zerolinecolor='#9CA3AF',
                    zerolinewidth=2
                ),
                yaxis=dict(
                    title=f'<b>PC2 ({varianza_explicada[1]:.1f}%)</b>',
                    showgrid=True,
                    gridcolor='#E5E7EB',
                    zeroline=True,
                    zerolinecolor='#9CA3AF',
                    zerolinewidth=2
                ),
                hovermode='closest',
                plot_bgcolor='#F9FAFB',
                paper_bgcolor='white',
                showlegend=True,
                legend=dict(
                    orientation="v",
                    yanchor="middle",
                    y=0.5,
                    xanchor="left",
                    x=1.02
                )
            )
            
            cluster_plot = {
                'data': cluster_traces,
                'layout': cluster_layout
            }
            
            # Guardar información de clusters para exportación
            request.session[f'pca_clusters_{proyecto_id}'] = {
                'articulos': df_numeric[['articulo_titulo', 'Cluster']].to_dict('records'),
                'n_clusters': n_clusters
            }
        
        # Convertir gráficos Plotly a formato JSON serializable
        def convert_numpy_to_list(obj):
            """Convierte recursivamente arrays de NumPy a listas"""
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, dict):
                return {key: convert_numpy_to_list(value) for key, value in obj.items()}
            elif isinstance(obj, list):
                return [convert_numpy_to_list(item) for item in obj]
            elif isinstance(obj, (np.integer, np.floating)):
                return float(obj)
            return obj
        
        def plotly_to_json(plot_dict):
            """Convierte un diccionario con objetos Plotly a JSON serializable"""
            if plot_dict is None:
                return None
            
            # Convertir traces a diccionarios
            data_json = []
            for trace in plot_dict['data']:
                # Usar el método to_plotly_json() si está disponible
                if hasattr(trace, 'to_plotly_json'):
                    trace_dict = trace.to_plotly_json()
                else:
                    # Si es un diccionario, usarlo directamente
                    trace_dict = trace
                
                # Convertir arrays de NumPy a listas
                trace_dict = convert_numpy_to_list(trace_dict)
                data_json.append(trace_dict)
            
            # Convertir layout a diccionario
            if hasattr(plot_dict['layout'], 'to_plotly_json'):
                layout_json = plot_dict['layout'].to_plotly_json()
            else:
                layout_json = plot_dict['layout']
            
            # Convertir arrays de NumPy en layout
            layout_json = convert_numpy_to_list(layout_json)
            
            return {
                'data': data_json,
                'layout': layout_json
            }
        
        scree_plot_json = plotly_to_json(scree_plot)
        biplot_json = plotly_to_json(biplot)
        cos2_plot_json = plotly_to_json(cos2_plot)
        correlation_circle_json = plotly_to_json(correlation_circle)
        cluster_plot_json = plotly_to_json(cluster_plot)
        
        # Retornar todos los gráficos
        return JsonResponse({
            'success': True,
            'total_articulos': articulos_query.count(),
            'articulos_con_datos': len(df_numeric),
            'plots': {
                'scree_plot': scree_plot_json,
                'biplot': biplot_json,
                'cos2_plot': cos2_plot_json,
                'correlation_circle': correlation_circle_json,
                'cluster_plot': cluster_plot_json
            }
        })
    
    except PlantillaBusqueda.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Plantilla no encontrada'}, status=404)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'Error interno: {str(e)}'}, status=500)


@login_required
def exportar_clusters_pca(request, proyecto_id):
    """
    Exporta los clusters del análisis PCA a un archivo Excel
    """
    try:
        # Obtener datos de clusters de la sesión
        cluster_data = request.session.get(f'pca_clusters_{proyecto_id}')
        
        if not cluster_data:
            return HttpResponse('No hay datos de clusters disponibles. Genera primero el análisis PCA.', status=400)
        
        # Crear DataFrame
        df = pd.DataFrame(cluster_data['articulos'])
        
        # Crear archivo Excel en memoria
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Clusters', index=False)
            
            # Formatear el Excel
            workbook = writer.book
            worksheet = writer.sheets['Clusters']
            
            # Encabezados en negrita
            for cell in worksheet[1]:
                cell.font = Font(bold=True, color='FFFFFF')
                cell.fill = PatternFill(start_color='366092', end_color='366092', fill_type='solid')
                cell.alignment = Alignment(horizontal='center', vertical='center')
            
            # Ajustar anchos de columna
            worksheet.column_dimensions['A'].width = 50
            worksheet.column_dimensions['B'].width = 15
            
            # Colorear filas según cluster
            colores_clusters = {1: 'C6D9F1', 2: 'F2DCDB', 3: 'D4EDDA'}
            for idx, row in enumerate(worksheet.iter_rows(min_row=2, max_row=len(df)+1), 2):
                cluster = df.iloc[idx-2]['Cluster']
                color = colores_clusters.get(cluster, 'FFFFFF')
                for cell in row:
                    cell.fill = PatternFill(start_color=color, end_color=color, fill_type='solid')
                    cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
        
        output.seek(0)
        
        # Preparar respuesta
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="clusters_pca_proyecto_{proyecto_id}.xlsx"'
        
        return response
        
    except Exception as e:
        return HttpResponse(f'Error al exportar clusters: {str(e)}', status=500)


@login_required
def guardar_pdf_doi(request, articulo_id):
    """
    Descarga y guarda automáticamente el PDF de un artículo desde su DOI
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    articulo = get_object_or_404(Articulo, id=articulo_id)
    
    # Verificar permisos: solo el usuario asignado o el creador del proyecto pueden guardar PDFs
    if not (request.user == articulo.usuario_asignado or request.user == articulo.proyecto.usuario_creador):
        return JsonResponse({'error': 'No tienes permisos para guardar PDFs en este artículo.'}, status=403)
    
    if articulo.archivo_pdf:
        return JsonResponse({'error': 'El artículo ya tiene un PDF guardado.'}, status=400)
    
    if not articulo.doi:
        return JsonResponse({'error': 'El artículo no tiene DOI.'}, status=400)
    
    try:
        # Obtener información del PDF
        pdf_info = obtener_pdf_desde_doi(articulo.doi)
        
        if not pdf_info.get('success', False):
            error_msg = pdf_info.get('error', 'No se pudo encontrar una versión open access del PDF.')
            return JsonResponse({'error': error_msg}, status=400)
        
        pdf_url = pdf_info['pdf_url']
        
        # Descargar el PDF
        response = requests.get(pdf_url, timeout=30)
        if response.status_code != 200:
            return JsonResponse({'error': 'No se pudo descargar el PDF desde la URL proporcionada.'}, status=400)
        
        pdf_content = response.content
        
        # Verificar que sea un PDF válido
        if not pdf_content.startswith(b'%PDF'):
            return JsonResponse({'error': 'La URL no contiene un archivo PDF válido.'}, status=400)
        
        # Generar nombre de archivo
        filename = f"{articulo.bibtex_key}.pdf"
        
        # Guardar el archivo
        articulo.archivo_pdf.save(filename, ContentFile(pdf_content))
        articulo.save()
        
        return JsonResponse({
            'success': 'PDF guardado exitosamente.',
            'fuente': pdf_info.get('fuente', 'Desconocida')
        })
        
    except requests.exceptions.Timeout:
        return JsonResponse({'error': 'Tiempo de espera agotado al descargar el PDF.'}, status=408)
    except requests.exceptions.RequestException as e:
        return JsonResponse({'error': f'Error de conexión: {str(e)}'}, status=500)
    except Exception as e:
        return JsonResponse({'error': f'Error interno: {str(e)}'}, status=500)


@login_required
def descargar_pdf(request, articulo_id):
    """
    Descarga el PDF guardado de un artículo (con descarga automática)
    """
    articulo = get_object_or_404(Articulo, id=articulo_id)
    
    # Verificar permisos
    if not (request.user == articulo.usuario_asignado or request.user == articulo.proyecto.usuario_creador):
        return JsonResponse({'error': 'No tienes permisos para descargar este PDF.'}, status=403)
    
    if not articulo.archivo_pdf:
        return JsonResponse({'error': 'Este artículo no tiene PDF guardado.'}, status=404)
    
    try:
        response = HttpResponse(articulo.archivo_pdf.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{articulo.bibtex_key}.pdf"'
        return response
    except Exception as e:
        return JsonResponse({'error': f'Error al descargar el PDF: {str(e)}'}, status=500)


@login_required
def visualizar_pdf(request, articulo_id):
    """
    Visualiza el PDF guardado de un artículo (inline, sin descarga automática)
    """
    articulo = get_object_or_404(Articulo, id=articulo_id)
    
    # Verificar que el usuario tenga acceso al proyecto
    usuario_proyecto = UsuarioProyecto.objects.filter(
        usuario=request.user,
        proyecto=articulo.proyecto
    ).first()
    
    if not usuario_proyecto:
        return JsonResponse({'error': 'No tienes acceso a este proyecto.'}, status=403)
    
    if not articulo.archivo_pdf:
        return JsonResponse({'error': 'Este artículo no tiene PDF guardado.'}, status=404)
    
    try:
        # Leer el contenido del archivo
        pdf_content = articulo.archivo_pdf.read()
        
        # Crear respuesta
        response = HttpResponse(pdf_content, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{articulo.bibtex_key}.pdf"'
        response['Content-Length'] = len(pdf_content)
        response['Cache-Control'] = 'public, max-age=3600'
        
        return response
    except Exception as e:
        print(f"ERROR visualizar_pdf: {str(e)}")
        return FileResponse(articulo.archivo_pdf.open('rb'), content_type='application/pdf')


@login_required
def eliminar_pdf(request, articulo_id):
    """
    Elimina el PDF guardado de un artículo
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    articulo = get_object_or_404(Articulo, id=articulo_id)
    
    # Verificar permisos
    if not (request.user == articulo.usuario_asignado or request.user == articulo.proyecto.usuario_creador):
        return JsonResponse({'error': 'No tienes permisos para eliminar este PDF.'}, status=403)
    
    if not articulo.archivo_pdf:
        return JsonResponse({'error': 'Este artículo no tiene PDF guardado.'}, status=404)
    
    try:
        # Eliminar el archivo
        articulo.archivo_pdf.delete()
        articulo.save()
        
        return JsonResponse({'success': 'PDF eliminado exitosamente'})
    except Exception as e:
        return JsonResponse({'error': f'Error al eliminar el PDF: {str(e)}'}, status=500)


@login_required
def exportar_coordenadas_biplot(request, proyecto_id):
    """
    Exporta las coordenadas X,Y del Biplot PCA a un archivo Excel
    """
    try:
        # Obtener datos del biplot de la sesión
        biplot_data = request.session.get(f'pca_biplot_{proyecto_id}')
        
        if not biplot_data:
            return HttpResponse('No hay datos del Biplot disponibles. Genera primero el análisis PCA.', status=400)
        
        # Crear DataFrame
        df = pd.DataFrame(biplot_data['articulos'])
        
        # Crear archivo Excel en memoria
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Coordenadas Biplot', index=False)
            
            # Formatear el Excel
            workbook = writer.book
            worksheet = writer.sheets['Coordenadas Biplot']
            
            # Encabezados en negrita con color
            for cell in worksheet[1]:
                cell.font = Font(bold=True, color='FFFFFF')
                cell.fill = PatternFill(start_color='366092', end_color='366092', fill_type='solid')
                cell.alignment = Alignment(horizontal='center', vertical='center')
            
            # Ajustar anchos de columna
            worksheet.column_dimensions['A'].width = 50  # articulo_titulo
            worksheet.column_dimensions['B'].width = 15  # X
            worksheet.column_dimensions['C'].width = 15  # Y
            
            # Formatear filas de datos
            for row in worksheet.iter_rows(min_row=2, max_row=len(df)+1):
                for cell in row:
                    cell.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
                    
            # Colorear filas de datos
            for idx, row in enumerate(worksheet.iter_rows(min_row=2, max_row=len(df)+1), 2):
                color = 'E7E6E6' if idx % 2 == 0 else 'FFFFFF'
                for cell in row:
                    if cell.fill.fill_type is None:
                        cell.fill = PatternFill(start_color=color, end_color=color, fill_type='solid')
        
        output.seek(0)
        
        # Preparar respuesta
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="coordenadas_biplot_proyecto_{proyecto_id}.xlsx"'
        
        return response
        
    except Exception as e:
        return HttpResponse(f'Error al exportar coordenadas: {str(e)}', status=500)


# ==================== ANÁLISIS DE ARTÍCULOS CON IA ====================

@login_required
def analizar_articulo_view(request, articulo_id):
    """
    Vista para iniciar análisis de un artículo con IA.
    - SUPERVISOR/DUEÑO: Pueden seleccionar/personalizar variables antes del análisis
    - COLABORADOR: Hace análisis directo con variables preseleccionadas de la plantilla
    """
    from .ia_analyzer import procesar_articulo_completo
    from .models import AnalisisArticulo
    
    try:
        articulo = Articulo.objects.get(id=articulo_id)
        proyecto = articulo.proyecto
        
        # Verificar permisos
        usuario_proyecto = UsuarioProyecto.objects.filter(
            usuario=request.user,
            proyecto=proyecto,
            rol_proyecto__in=['SUPERVISOR', 'DUEÑO', 'COLABORADOR']
        ).first()
        
        if not usuario_proyecto:
            messages.error(request, "No tienes permiso para analizar artículos en este proyecto.")
            return redirect('articulos:ver_articulos', proyecto.id)
        
        # Obtener plantilla del proyecto
        plantilla = PlantillaBusqueda.objects.filter(
            proyecto=proyecto,
            es_predeterminada=True
        ).first()
        
        if not plantilla:
            messages.error(request, "El proyecto no tiene variables configuradas.")
            return redirect('articulos:ver_articulos', proyecto.id)
        
        # Obtener campos (variables) de la plantilla
        campos_plantilla = plantilla.campos.all()
        
        # SUPERVISORES y DUEÑO: pueden personalizar variables
        puede_personalizar = usuario_proyecto.rol_proyecto in ['SUPERVISOR', 'DUEÑO']
        
        # Campos adicionales disponibles (para SUPERVISOR y DUEÑO)
        campos_globales = CampoMetanalisis.objects.filter(proyecto__isnull=True, activo=True) if puede_personalizar else []
        campos_proyecto = CampoMetanalisis.objects.filter(proyecto=proyecto, activo=True) if puede_personalizar else []
        campos_disponibles = (campos_globales | campos_proyecto) if puede_personalizar else []
        
        # Para COLABORADOR: lanzar análisis directamente sin interfaz
        if not puede_personalizar:
            resultado = procesar_articulo_completo(
                articulo=articulo,
                campos_a_buscar=campos_plantilla,
                usuario=request.user
            )
            
            if resultado['exito']:
                messages.success(
                    request,
                    f"✅ Análisis completado en {resultado['detalles']['tiempo']:.2f}s | "
                    f"Tokens: {resultado['detalles']['tokens']}"
                )
                return redirect('articulos:ver_resultados_analisis', resultado['analisis'].id)
            else:
                messages.error(request, f"❌ Error: {resultado['mensaje']}")
                return redirect('articulos:ver_articulos', proyecto.id)
        
        # Para SUPERVISOR/DUEÑO: mostrar interfaz de selección
        if request.method == 'POST':
            # SUPERVISOR/DUEÑO: pueden seleccionar variables personalizadas
            campos_ids = request.POST.getlist('campos_seleccionados')
            
            if not campos_ids:
                messages.error(request, "Debes seleccionar al menos una variable para analizar.")
                campos_para_analizar = campos_plantilla
            else:
                campos_para_analizar = CampoMetanalisis.objects.filter(id__in=campos_ids)
            
            # Iniciar análisis
            resultado = procesar_articulo_completo(
                articulo=articulo,
                campos_a_buscar=campos_para_analizar,
                usuario=request.user
            )
            
            if resultado['exito']:
                messages.success(
                    request,
                    f"✅ Análisis completado en {resultado['detalles']['tiempo']:.2f}s | "
                    f"Tokens: {resultado['detalles']['tokens']}"
                )
                return redirect('articulos:ver_resultados_analisis', resultado['analisis'].id)
            else:
                messages.error(request, f"❌ Error: {resultado['mensaje']}")
        
        context = {
            'articulo': articulo,
            'proyecto': proyecto,
            'campos_plantilla': campos_plantilla,
            'campos_disponibles': campos_disponibles,
            'analisis_previo': articulo.analisis_ia.first(),
            'puede_personalizar': puede_personalizar,
            'rol_usuario': usuario_proyecto.rol_proyecto,
        }
        
        return render(request, 'analizar_articulo.html', context)
    
    except Articulo.DoesNotExist:
        messages.error(request, "Artículo no encontrado.")
        return redirect('mis_proyectos')
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        return redirect('mis_proyectos')


@login_required
@login_required
def obtener_sugerencias_analisis(request, articulo_id):
    """
    API que devuelve los datos del último análisis de un artículo en JSON.
    Los campos se autocompletan en workspace.html SIN guardar automáticamente.
    El usuario visualiza primero y luego decide guardar manualmente.
    """
    from .models import AnalisisArticulo
    import json
    
    try:
        articulo = get_object_or_404(Articulo, id=articulo_id)
        proyecto = articulo.proyecto
        
        # Verificar permisos
        usuario_proyecto = UsuarioProyecto.objects.filter(
            usuario=request.user,
            proyecto=proyecto
        ).first()
        
        if not usuario_proyecto:
            return JsonResponse({'success': False, 'error': 'No tienes permisos'}, status=403)
        
        # Obtener el último análisis completado
        analisis = AnalisisArticulo.objects.filter(
            articulo=articulo,
            estado='COMPLETADO'
        ).order_by('-fecha_analisis').first()
        
        if not analisis:
            return JsonResponse({
                'success': False,
                'error': 'No hay análisis completado para este artículo',
                'sugerencias': {}
            })
        
        # Extraer campos y valores del análisis
        sugerencias = {}
        
        # Procesar cada campo analizado
        for campo in analisis.campos_analizados.all():
            codigo = campo.codigo
            tipo_datos = campo.tipo_dato
            dato_ia = analisis.resultados.get(codigo, {})
            
            if dato_ia.get('encontrado', False):
                contexto = dato_ia.get('contexto', '')
                
                # Para campos numéricos: intentar extraer número
                if tipo_datos == 'NUMERO':
                    # Intentar extraer número del contexto
                    import re
                    numeros = re.findall(r'\d+(?:\.\d+)?', contexto)
                    valor = numeros[0] if numeros else contexto
                else:
                    valor = contexto
                
                sugerencias[codigo] = {
                    'valor': valor,
                    'contexto': contexto,
                    'cita': dato_ia.get('cita_textual', ''),
                    'confianza': dato_ia.get('confianza', 'media')
                }
        
        return JsonResponse({
            'success': True,
            'sugerencias': sugerencias,
            'fecha_analisis': analisis.fecha_analisis.isoformat()
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
            'sugerencias': {}
        }, status=500)


def ver_resultados_analisis(request, analisis_id):
    """
    Vista para ver resultados detallados de un análisis.
    Muestra tabla con variables encontradas / no encontradas + método de análisis.
    """
    from .models import AnalisisArticulo
    
    try:
        analisis = AnalisisArticulo.objects.select_related('articulo', 'proyecto').get(id=analisis_id)
        articulo = analisis.articulo
        proyecto = analisis.proyecto
        
        # Verificar permisos
        usuario_proyecto = UsuarioProyecto.objects.filter(
            usuario=request.user,
            proyecto=proyecto
        ).first()
        
        if not usuario_proyecto:
            messages.error(request, "No tienes permiso para ver este análisis.")
            return redirect('articulos:ver_articulos', proyecto.id)
        
        # Procesar resultados para mostrar en tabla
        campos_analizados = analisis.campos_analizados.all()
        
        # Construir datos para tabla
        tabla_resultados = []
        encontrados = 0
        no_encontrados = 0
        
        # 🔹 AGREGAR MÉTODO DE ANÁLISIS DE DATOS
        metodo_analisis_dato = analisis.resultados.get('metodo_analisis_datos', {})
        if metodo_analisis_dato:
            encontrado_metodo = metodo_analisis_dato.get('encontrado', False)
            tabla_resultados.append({
                'campo': type('obj', (object,), {
                    'nombre': '📊 Método de Análisis de Datos',
                    'codigo': 'metodo_analisis_datos',
                    'categoria': 'METODOLOGIA',
                    'get_categoria_display': lambda: 'METODOLOGIA'
                })(),
                'encontrado': encontrado_metodo,
                'contexto': metodo_analisis_dato.get('contexto', '-'),
                'cita_textual': metodo_analisis_dato.get('cita_textual', '-'),
                'confianza': metodo_analisis_dato.get('confianza', '-'),
                'icono': '✅' if encontrado_metodo else '❌',
                'es_metodo_analisis': True,  # Marcador especial para el template
            })
            if encontrado_metodo:
                encontrados += 1
            else:
                no_encontrados += 1
        
        # 🔹 AGREGAR LAS VARIABLES NORMALES
        for campo in campos_analizados:
            codigo = campo.codigo
            dato_ia = analisis.resultados.get(codigo, {})
            
            encontrado = dato_ia.get('encontrado', False)
            contexto = dato_ia.get('contexto', '-')
            cita_textual = dato_ia.get('cita_textual', '-')
            confianza = dato_ia.get('confianza', '-')
            
            if encontrado:
                encontrados += 1
            else:
                no_encontrados += 1
            
            tabla_resultados.append({
                'campo': campo,
                'encontrado': encontrado,
                'contexto': contexto,
                'cita_textual': cita_textual,
                'confianza': confianza,
                'icono': '✅' if encontrado else '❌',
            })
        
        # Estadísticas (sin contar el método de análisis en el total)
        total_campos = len(campos_analizados)
        porcentaje_encontrados = (encontrados / (total_campos + 1) * 100) if total_campos > 0 else 0
        
        context = {
            'analisis': analisis,
            'articulo': articulo,
            'proyecto': proyecto,
            'tabla_resultados': tabla_resultados,
            'metodo_analisis': metodo_analisis_dato if metodo_analisis_dato else None,
            'estadisticas': {
                'total': total_campos,
                'encontrados': encontrados,
                'no_encontrados': no_encontrados,
                'porcentaje': round(porcentaje_encontrados, 1),
            }
        }
        
        return render(request, 'resultados_analisis.html', context)
    
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        return redirect('mis_proyectos')


@login_required
def listar_analisis_proyecto(request, proyecto_id):
    """
    Vista para listar todos los análisis de un proyecto.
    Accesible desde la pestaña "Análisis de Artículos" en supervisión.
    """
    from .models import AnalisisArticulo
    
    try:
        proyecto = Proyecto.objects.get(id=proyecto_id)
        
        # Verificar permisos
        usuario_proyecto = UsuarioProyecto.objects.filter(
            usuario=request.user,
            proyecto=proyecto,
            rol_proyecto__in=['SUPERVISOR', 'DUEÑO']
        ).first()
        
        if not usuario_proyecto:
            messages.error(request, "No tienes permiso para ver análisis de este proyecto.")
            return redirect('mis_proyectos')
        
        # Obtener análisis del proyecto
        analisis_list = AnalisisArticulo.objects.filter(
            proyecto=proyecto
        ).select_related('articulo', 'analizado_por').order_by('-fecha_analisis')
        
        # Paginación
        paginator = Paginator(analisis_list, 10)
        page_number = request.GET.get('page', 1)
        analisis_page = paginator.get_page(page_number)
        
        # Estadísticas generales
        estadisticas = {
            'total_analisis': analisis_list.count(),
            'completados': analisis_list.filter(estado='COMPLETADO').count(),
            'errores': analisis_list.filter(estado='ERROR').count(),
            'pendientes': analisis_list.filter(estado='PENDIENTE').count(),
        }
        
        context = {
            'proyecto': proyecto,
            'analisis_page': analisis_page,
            'paginator': paginator,
            'estadisticas': estadisticas,
        }
        
        return render(request, 'listar_analisis_proyecto.html', context)
    
    except Proyecto.DoesNotExist:
        messages.error(request, "Proyecto no encontrado.")
        return redirect('mis_proyectos')
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        return redirect('mis_proyectos')

