from django import forms
from .models import Profesional

class ProfesionalForm(forms.ModelForm):
    class Meta:
        model = Profesional
        fields = ['foto', 'nombre', 'apellido', 'especialidad', 'telefono', 'email', 
                  'servicios', 'sucursales', 'activo', 'user']
        widgets = {
            'foto': forms.FileInput(attrs={
                'class': 'w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-green-50 file:text-green-700 hover:file:bg-green-100',
                'accept': 'image/*'
            }),
            'nombre': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-green-400 text-sm font-bold',
                'placeholder': 'Ej: Juan'
            }),
            'apellido': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-green-400 text-sm font-bold',
                'placeholder': 'Ej: Pérez'
            }),
            'especialidad': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-green-400 text-sm font-bold',
                'placeholder': 'Ej: Terapia del Lenguaje'
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 text-sm font-bold',
                'placeholder': '7XXXXXXX'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 text-sm font-bold',
                'placeholder': 'correo@ejemplo.com'
            }),
            'servicios': forms.CheckboxSelectMultiple(attrs={
                'class': 'space-y-2'
            }),
            'sucursales': forms.CheckboxSelectMultiple(attrs={
                'class': 'space-y-2'
            }),
            'activo': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-green-600 border-gray-300 rounded focus:ring-green-500'
            }),
            'user': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-purple-400 text-sm font-bold'
            }),
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Hacer campos opcionales
        self.fields['telefono'].required = False
        self.fields['email'].required = False
        self.fields['user'].required = False
        self.fields['foto'].required = False
        
        # Personalizar labels
        self.fields['foto'].label = 'Foto del Profesional'
        self.fields['nombre'].label = 'Nombre'
        self.fields['apellido'].label = 'Apellido'
        self.fields['especialidad'].label = 'Especialidad'
        self.fields['telefono'].label = 'Teléfono'
        self.fields['email'].label = 'Email'
        self.fields['servicios'].label = 'Servicios que ofrece'
        self.fields['sucursales'].label = 'Sucursales donde trabaja'
        self.fields['activo'].label = 'Profesional activo'
        self.fields['user'].label = 'Usuario del sistema'