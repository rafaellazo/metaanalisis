# usuarios/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from .models import Profile, Role
from .forms import CustomUserCreationForm # Importa el nuevo formulario

# Desregistra el modelo User original para poder personalizarlo
admin.site.unregister(User)

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    # Usa el formulario personalizado para la creación de usuarios
    add_form = CustomUserCreationForm

    # Define los campos que se mostrarán en la lista de usuarios
    list_display = ('email', 'is_staff')

    # Oculta campos no deseados
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    # Define los campos para la edición
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password', 'password2'), # Usa password y password2 para confirmación
        }),
    )

    ordering = ('email',)

# Mantén el registro de tus modelos Profile y Role
admin.site.register(Profile)
admin.site.register(Role)
