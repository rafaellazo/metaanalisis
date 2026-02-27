from django import forms
from .models import ArchivoSubida

class ArchivoSubidaForm(forms.ModelForm):
    class Meta:
        model = ArchivoSubida
        fields = ['nombre_archivo', 'ruta_archivo']

    def clean_ruta_archivo(self):
        archivo = self.cleaned_data.get('ruta_archivo')
        if archivo:
            extension = archivo.name.split('.')[-1].lower()
            if extension not in ['bib']:
                raise forms.ValidationError("Solo se permiten archivos .pdf o .bib")
        return archivo
