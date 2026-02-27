# Generated migration for AnalisisArticulo model

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('articulos', '0014_alter_articulo_estado_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AnalisisArticulo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('resultados', models.JSONField(help_text='JSON con estructura: {"campo_id": {"encontrado": bool, "contexto": str, "evidencia": str}}')),
                ('estado', models.CharField(choices=[('PENDIENTE', 'Pendiente de Análisis'), ('PROCESANDO', 'Procesando...'), ('COMPLETADO', 'Completado'), ('ERROR', 'Error en Análisis')], default='PENDIENTE', max_length=20)),
                ('tokens_utilizados', models.IntegerField(blank=True, help_text='Cantidad de tokens usados en la llamada a OpenAI', null=True)),
                ('costo_estimado', models.DecimalField(blank=True, decimal_places=4, help_text='Costo estimado en USD', max_digits=10, null=True)),
                ('tiempo_procesamiento', models.IntegerField(blank=True, help_text='Tiempo en segundos', null=True)),
                ('fecha_analisis', models.DateTimeField(auto_now_add=True)),
                ('fecha_actualizacion', models.DateTimeField(auto_now=True)),
                ('mensaje_error', models.TextField(blank=True, help_text='Mensaje de error si algo falló')),
                ('validado', models.BooleanField(default=False, help_text='Supervisor confirmó que los resultados son correctos')),
                ('notas_validacion', models.TextField(blank=True, help_text='Observaciones del supervisor tras revisar')),
                ('analizado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='analisis_realizados', to=settings.AUTH_USER_MODEL)),
                ('articulo', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='analisis_ia', to='articulos.articulo')),
                ('campos_analizados', models.ManyToManyField(help_text='Campos que fueron buscados en el análisis', related_name='analisis', to='articulos.campometanalisis')),
                ('proyecto', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='analisis_articulos', to='pymetanalis.proyecto')),
            ],
            options={
                'verbose_name': 'Análisis de Artículo (IA)',
                'verbose_name_plural': 'Análisis de Artículos (IA)',
                'ordering': ['-fecha_analisis'],
            },
        ),
        migrations.AddIndex(
            model_name='analisisarticulo',
            index=models.Index(fields=['articulo', '-fecha_analisis'], name='articulos_a_articul_idx'),
        ),
        migrations.AddIndex(
            model_name='analisisarticulo',
            index=models.Index(fields=['proyecto', '-fecha_analisis'], name='articulos_a_proyec_idx'),
        ),
        migrations.AddIndex(
            model_name='analisisarticulo',
            index=models.Index(fields=['estado'], name='articulos_a_estado_idx'),
        ),
    ]
