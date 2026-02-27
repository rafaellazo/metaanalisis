# Generated migration for Open Access support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('articulos', '0014_alter_articulo_estado_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='articulo',
            name='es_open_access',
            field=models.BooleanField(blank=True, default=None, help_text='¿Está disponible en Open Access? (Consultado desde Unpaywall API)', null=True),
        ),
        migrations.AddField(
            model_name='articulo',
            name='url_open_access',
            field=models.URLField(blank=True, help_text='URL del PDF en Open Access (si está disponible)', null=True),
        ),
    ]
