from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from .models import Profile
from django.core.exceptions import ValidationError

class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(
        required=True, 
        label="Correo electrónico",
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'ejemplo@correo.com'
        })
    )
    first_name = forms.CharField(
        max_length=30, 
        required=True, 
        label="Nombre",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Tu nombre'
        })
    )
    last_name = forms.CharField(
        max_length=30, 
        required=True, 
        label="Apellidos",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Tus apellidos'
        })
    )
    
    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "password1", "password2")
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Personalizar los campos de contraseña
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Contraseña'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Confirmar contraseña'
        })
        
        # Quitar el campo username de la renderización
        if 'username' in self.fields:
            del self.fields['username']
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError("Ya existe un usuario con este correo electrónico.")
        return email
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"].title()  # Capitalizar
        user.last_name = self.cleaned_data["last_name"].title()    # Capitalizar
        user.username = self.cleaned_data["email"]  # Usar email como username
        
        if commit:
            user.save()
        return user

class CustomLoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Personalizar el campo username (que usaremos como email)
        self.fields['username'].label = "Correo electrónico"
        self.fields['username'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'ejemplo@correo.com',
            'type': 'email'
        })
        
        # Personalizar el campo password
        self.fields['password'].label = "Contraseña"
        self.fields['password'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Tu contraseña'
        })