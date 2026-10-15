import logging
import threading
from datetime import datetime, time, timedelta
from decimal import Decimal

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    AlertaSaldo, CalibracionSaldo, EstadoSincronizacion, GastoOpenAI,
    RegistroConsumoIA,
)
from pymetanalis.models import Notificacion

logger = logging.getLogger(__name__)


def calibracion_vigente():
    return CalibracionSaldo.objects.select_related('registrado_por').first()


def gasto_desde_calibracion(calibracion=None):
    calibracion = calibracion or calibracion_vigente()
    if not calibracion:
        return Decimal('0')

    inicio = timezone.localtime(calibracion.fecha_calibracion)
    hoy = timezone.localdate()
    total = Decimal('0')
    dia = inicio.date()
    while dia <= hoy:
        siguiente = dia + timedelta(days=1)
        gasto_real = (None if dia == inicio.date()
                      else GastoOpenAI.objects.filter(fecha=dia).first())
        if gasto_real:
            total += gasto_real.costo_real
        else:
            filtros = {'fecha__date': dia}
            if dia == inicio.date():
                filtros['fecha__gt'] = calibracion.fecha_calibracion
            total += (RegistroConsumoIA.objects.filter(**filtros)
                      .aggregate(total=Sum('costo_usd'))['total'] or Decimal('0'))
        dia = siguiente
    return total


def saldo_actual():
    calibracion = calibracion_vigente()
    if not calibracion:
        return None
    return calibracion.saldo_base - gasto_desde_calibracion(calibracion)


def porcentaje_restante():
    calibracion = calibracion_vigente()
    saldo = saldo_actual()
    if not calibracion or saldo is None or not calibracion.saldo_base:
        return None
    return max(Decimal('0'), min(Decimal('100'),
                saldo / calibracion.saldo_base * Decimal('100')))


def estado_saldo():
    porcentaje = porcentaje_restante()
    if porcentaje is None:
        return None
    if porcentaje <= 10:
        return 'critico'
    if porcentaje <= 20:
        return 'bajo'
    if porcentaje <= 50:
        return 'medio'
    return 'ok'


def _administradores():
    return User.objects.filter(is_superuser=True) | User.objects.filter(
        profile__role__name='administrador'
    )


def revisar_alertas_saldo():
    try:
        calibracion = calibracion_vigente()
        saldo = saldo_actual()
        porcentaje = porcentaje_restante()
        if not calibracion or saldo is None or porcentaje is None:
            return
        umbrales = [u for u in settings.UMBRALES_ALERTA if porcentaje <= u]
        if saldo <= settings.SALDO_MINIMO_USD:
            umbrales.append(0)
        for umbral in set(umbrales):
            alerta, creada = AlertaSaldo.objects.get_or_create(
                calibracion=calibracion, umbral=umbral
            )
            if not creada:
                continue
            estado = 'mínimo' if umbral == 0 else f'{umbral}%'
            for usuario in _administradores().distinct():
                Notificacion.objects.create(
                    usuario=usuario,
                    tipo='alerta_saldo',
                    titulo=f'Alerta de saldo IA ({estado})',
                    mensaje=f'Saldo disponible: ${saldo:.2f} ({porcentaje:.1f}%).',
                    url='/articulos/consumo/',
                )
    except Exception:
        logger.exception('No se pudo revisar las alertas de saldo')


def registrar_consumo(resultado, articulo, campos_a_buscar, usuario, analisis=None):
    from pymetanalis import settings as project_settings
    entrada = resultado.get('tokens_entrada', 0)
    cacheados = resultado.get('tokens_cacheados', 0)
    salida = resultado.get('tokens_salida', 0)
    costo = project_settings.calcular_costo_usd(entrada, cacheados, salida)
    registro = RegistroConsumoIA.objects.create(
        usuario=usuario,
        proyecto=articulo.proyecto,
        proyecto_nombre=articulo.proyecto.nombre,
        articulo=articulo,
        articulo_titulo=articulo.titulo,
        archivo_bib=articulo.archivo_bib or 'Sin archivo .bib',
        analisis=analisis,
        modelo=project_settings.OPENAI_MODELO_ANALISIS,
        num_variables=campos_a_buscar.count(),
        tokens_entrada=entrada,
        tokens_cacheados=cacheados,
        tokens_salida=salida,
        precio_entrada_usado=project_settings.PRECIO_ENTRADA_POR_MILLON,
        precio_cache_usado=project_settings.PRECIO_ENTRADA_CACHE_POR_MILLON,
        precio_salida_usado=project_settings.PRECIO_SALIDA_POR_MILLON,
        costo_usd=costo,
        exito=resultado.get('exito', False),
        mensaje_error=resultado.get('error') or '',
    )
    revisar_alertas_saldo()
    return registro


def sincronizar_gasto_openai():
    calibracion = calibracion_vigente()
    if not calibracion or not settings.OPENAI_ADMIN_KEY:
        return False
    try:
        response = requests.get(
            'https://api.openai.com/v1/organization/costs',
            params={
                'bucket_width': '1d',
                'start_time': int(calibracion.fecha_calibracion.timestamp()),
                **({'project_ids[]': settings.OPENAI_PROJECT_ID}
                   if settings.OPENAI_PROJECT_ID else {}),
            },
            headers={'Authorization': f'Bearer {settings.OPENAI_ADMIN_KEY}'},
            timeout=20,
        )
        if response.status_code in (401, 403, 404):
            logger.warning('OpenAI costs respondió %s', response.status_code)
            return False
        response.raise_for_status()
        for bucket in response.json().get('data', []):
            fecha = datetime.fromtimestamp(bucket['start_time'], tz=timezone.utc).date()
            amount = sum(Decimal(str(item.get('amount', {}).get('value', 0)))
                         for item in bucket.get('results', []))
            GastoOpenAI.objects.update_or_create(
                fecha=fecha, defaults={'costo_real': amount, 'moneda': 'USD'}
            )
        revisar_alertas_saldo()
        return True
    except (requests.RequestException, ValueError, KeyError):
        logger.exception('No se pudo sincronizar el gasto de OpenAI')
        return False


def _sincronizar_en_hilo():
    try:
        sincronizar_gasto_openai()
    finally:
        EstadoSincronizacion.objects.filter(unica=True).update(
            en_curso=False, ultima_sincronizacion=timezone.now()
        )


def sincronizar_si_corresponde():
    try:
        estado, _ = EstadoSincronizacion.objects.get_or_create(unica=True)
        limite = timezone.now() - timedelta(minutes=settings.SYNC_MIN_INTERVALO_MINUTOS)
        if estado.en_curso or (estado.ultima_sincronizacion and
                               estado.ultima_sincronizacion > limite):
            return
        with transaction.atomic():
            actualizado = EstadoSincronizacion.objects.filter(
                pk=estado.pk, en_curso=False
            ).filter(
                ultima_sincronizacion__isnull=True
            ).update(en_curso=True)
            if not actualizado:
                actualizado = EstadoSincronizacion.objects.filter(
                    pk=estado.pk, en_curso=False,
                    ultima_sincronizacion__lt=limite
                ).update(en_curso=True)
        if actualizado:
            threading.Thread(target=_sincronizar_en_hilo, daemon=True).start()
    except Exception:
        logger.exception('No se pudo programar la sincronización de OpenAI')
