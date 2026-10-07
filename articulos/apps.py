from django.apps import AppConfig


class ArticulosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'articulos'

    def ready(self):
        # Registra los signals (crea la plantilla base al crear un proyecto)
        from . import signals  # noqa: F401
