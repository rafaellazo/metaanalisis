from django.test import TestCase
from pymetanalis import settings
from django.db import models
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta

from .models import CalibracionSaldo, GastoOpenAI, RegistroConsumoIA
from .servicios_saldo import gasto_desde_calibracion, saldo_actual

class ConsumoIATests(TestCase):
    def test_calcular_costo_usd(self):
        costo = settings.calcular_costo_usd(1_000_000, 100_000, 500_000)
        esperado = (Decimal('900000') / Decimal('1000000') * settings.PRECIO_ENTRADA_POR_MILLON
                    + Decimal('100000') / Decimal('1000000') * settings.PRECIO_ENTRADA_CACHE_POR_MILLON
                    + Decimal('500000') / Decimal('1000000') * settings.PRECIO_SALIDA_POR_MILLON)
        self.assertEqual(costo, esperado.quantize(Decimal('0.000001')))

    def test_saldo_prefiere_gasto_real_sin_doble_conteo(self):
        calibracion = CalibracionSaldo.objects.create(saldo_base=Decimal('10'))
        registro = RegistroConsumoIA.objects.create(
            modelo='test', precio_entrada_usado=0, precio_cache_usado=0,
            precio_salida_usado=0, costo_usd=Decimal('1'), exito=True,
        )
        RegistroConsumoIA.base_objects.filter(pk=registro.pk).update(
            fecha=calibracion.fecha_calibracion + timedelta(minutes=1)
        )
        GastoOpenAI.objects.create(fecha=timezone.localdate() + timedelta(days=1),
                                   costo_real=Decimal('2'))
        self.assertEqual(gasto_desde_calibracion(calibracion), Decimal('1'))
        self.assertEqual(saldo_actual(), Decimal('9'))

    def test_registro_no_se_puede_editar_ni_borrar(self):
        registro = RegistroConsumoIA.objects.create(
            modelo='test', precio_entrada_usado=0, precio_cache_usado=0,
            precio_salida_usado=0, costo_usd=Decimal('1'), exito=True,
        )
        with self.assertRaises(models.ProtectedError):
            registro.delete()
        with self.assertRaises(models.ProtectedError):
            RegistroConsumoIA.objects.filter(pk=registro.pk).update(costo_usd=2)
