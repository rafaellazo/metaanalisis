import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Max, Min, Sum, Count, Q
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from usuarios.views import is_admin_or_superuser
from .models import CalibracionSaldo, EstadoSincronizacion, RegistroConsumoIA
from .servicios_saldo import (
    calibracion_vigente, estado_saldo, gasto_desde_calibracion,
    porcentaje_restante, saldo_actual, sincronizar_si_corresponde,
)


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not is_admin_or_superuser(request.user):
            return HttpResponseForbidden('Solo los administradores pueden acceder.')
        return view(request, *args, **kwargs)
    return wrapped


@admin_required
def panel_consumo(request):
    sincronizar_si_corresponde()
    calibracion = calibracion_vigente()
    registros = RegistroConsumoIA.objects.all()
    por_dia = registros.values('fecha__date').annotate(total=Sum('costo_usd')).order_by('fecha__date')
    context = {
        'calibracion': calibracion,
        'saldo': saldo_actual(),
        'porcentaje': porcentaje_restante(),
        'estado': estado_saldo(),
        'gasto_registrado': gasto_desde_calibracion(),
        'gasto_real': None,
        'por_dia': list(por_dia),
        'ultima_sincronizacion': getattr(
            EstadoSincronizacion.objects.filter(unica=True).first(),
            'ultima_sincronizacion', None
        ),
    }
    return render(request, 'panel_consumo.html', context)


@admin_required
def historial_consumo(request):
    qs = RegistroConsumoIA.objects.select_related('usuario', 'proyecto', 'articulo')
    if request.GET.get('desde'):
        qs = qs.filter(fecha__date__gte=request.GET['desde'])
    if request.GET.get('hasta'):
        qs = qs.filter(fecha__date__lte=request.GET['hasta'])
    if request.GET.get('proyecto'):
        qs = qs.filter(proyecto_id=request.GET['proyecto'])
    if request.GET.get('usuario'):
        qs = qs.filter(usuario_id=request.GET['usuario'])
    if request.GET.get('archivo'):
        qs = qs.filter(archivo_bib__icontains=request.GET['archivo'])
    if request.GET.get('tipo_operacion'):
        qs = qs.filter(tipo_operacion=request.GET['tipo_operacion'])
    if request.GET.get('resultado') in ('1', '0'):
        qs = qs.filter(exito=request.GET['resultado'] == '1')
    if request.GET.get('buscar'):
        qs = qs.filter(articulo_titulo__icontains=request.GET['buscar'])
    try:
        if request.GET.get('costo_min'):
            qs = qs.filter(costo_usd__gte=Decimal(request.GET['costo_min']))
        if request.GET.get('costo_max'):
            qs = qs.filter(costo_usd__lte=Decimal(request.GET['costo_max']))
    except InvalidOperation:
        pass
    orden = request.GET.get('orden', 'reciente')
    qs = qs.order_by({'antiguo': 'fecha', 'mayor': '-costo_usd',
                      'menor': 'costo_usd'}.get(orden, '-fecha'))
    resumen = qs.aggregate(total=Sum('costo_usd'), cantidad=Count('id'),
                           promedio=Avg('costo_usd'), mayor=Max('costo_usd'),
                           menor=Min('costo_usd'))
    page = Paginator(qs, 25).get_page(request.GET.get('page'))
    if request.GET.get('formato') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="historial_consumo.csv"'
        writer = csv.writer(response)
        writer.writerow(['Fecha', 'Artículo', 'Proyecto', 'Archivo .bib', 'Usuario',
                         'Operación', 'Variables', 'Costo USD', 'Éxito'])
        for item in qs:
            writer.writerow([item.fecha, item.articulo_titulo, item.proyecto_nombre,
                             item.archivo_bib, item.usuario, item.tipo_operacion,
                             item.num_variables, item.costo_usd, item.exito])
        return response
    return render(request, 'historial_consumo.html', {
        'registros': page, 'resumen': resumen, 'filtros': request.GET,
    })


@admin_required
def saldo_json(request):
    sincronizar_si_corresponde()
    saldo = saldo_actual()
    return JsonResponse({
        'saldo': str(saldo.quantize(Decimal('0.01'))) if saldo is not None else None,
        'porcentaje': float(porcentaje_restante()) if porcentaje_restante() is not None else None,
        'estado': estado_saldo(),
        'calibrado': saldo is not None,
    })


@admin_required
@require_POST
def recalibrar_saldo(request):
    try:
        saldo = Decimal(request.POST.get('saldo_base', ''))
        if saldo < 0:
            raise InvalidOperation
    except (InvalidOperation, TypeError):
        messages.error(request, 'Introduce un saldo válido en USD.')
        return redirect('articulos:panel_consumo')
    CalibracionSaldo.objects.create(
        saldo_base=saldo, registrado_por=request.user,
        nota=request.POST.get('nota', '').strip(),
    )
    messages.success(request, 'Saldo recalibrado correctamente.')
    return redirect('articulos:panel_consumo')
