from django.core.management.base import BaseCommand

from articulos.servicios_saldo import sincronizar_gasto_openai


class Command(BaseCommand):
    help = 'Sincroniza el gasto real de OpenAI (el módulo también funciona sin cron).'

    def handle(self, *args, **options):
        if sincronizar_gasto_openai():
            self.stdout.write(self.style.SUCCESS('Gasto de OpenAI sincronizado.'))
        else:
            self.stdout.write(self.style.WARNING(
                'No se sincronizó: falta calibración, clave administrativa o hubo un error.'
            ))
