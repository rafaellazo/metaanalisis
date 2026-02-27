from django.apps import AppConfig

class UsuariosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'usuarios'

    def ready(self):
        from django.db.models.signals import post_migrate
        from django.apps import apps
        from django.dispatch import receiver

        @receiver(post_migrate)
        def create_default_roles(sender, **kwargs):
            # Solo ejecutarse cuando se migra la app 'usuarios'
            if sender.name == self.name:
                Role = apps.get_model(self.name, 'Role')

                # Lista de roles que deben existir
                default_roles = [
                    'administrador',
                    'investigador',
                    'invitado',
                ]

                for role_name in default_roles:
                    Role.objects.get_or_create(name=role_name)
