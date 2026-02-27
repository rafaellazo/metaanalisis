# articulos/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from pymetanalis.models import Proyecto
from .models import PlantillaBusqueda, CampoMetanalisis
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Proyecto)
def crear_plantilla_proyecto(sender, instance, created, **kwargs):
    """
    Signal que crea automáticamente una plantilla base cuando se crea un proyecto nuevo
    """
    if created:
        try:
            # Obtener campos predefinidos más comunes del sistema
            campos_base = CampoMetanalisis.objects.filter(
                proyecto__isnull=True,
                activo=True,
                es_predefinido=True
            ).order_by('id')[:8]  # Primeros 8 campos más básicos
            
            # Crear plantilla del proyecto
            plantilla = PlantillaBusqueda.objects.create(
                nombre=f"Plantilla Principal - {instance.nombre}",
                descripcion=f"Plantilla base del proyecto {instance.nombre}. Esta plantilla se aplica automáticamente a todos los artículos. Puedes editarla agregando o quitando campos según tus necesidades.",
                proyecto=instance,
                creado_por=instance.usuario_creador,
                es_predeterminada=True
            )
            
            # Asignar campos base si existen
            if campos_base.exists():
                plantilla.campos.set(campos_base)
                logger.info(f"✅ Plantilla '{plantilla.nombre}' creada con {campos_base.count()} campos")
            else:
                logger.warning(f"⚠️ Plantilla '{plantilla.nombre}' creada sin campos (no hay campos predefinidos)")
        
        except Exception as e:
            logger.error(f"❌ Error al crear plantilla para proyecto {instance.nombre}: {str(e)}")