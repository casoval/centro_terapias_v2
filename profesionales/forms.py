from django import forms
from django.core.exceptions import ValidationError
from .models import Profesional

class ProfesionalForm(forms.ModelForm):
    """Formulario para crear/editar profesionales"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # ✅ FILTRAR: Solo usuarios con rol "profesional" que NO estén vinculados
        from core.models import PerfilUsuario
        from django.contrib.auth.models import User
        
        # Usuarios con rol profesional
        usuarios_profesional = User.objects.filter(
            perfil__rol='profesional'
        ).exclude(is_superuser=True)
        
        # Excluir los que ya tienen profesional vinculado
        usuarios_profesional = usuarios_profesional.exclude(
            perfil__profesional__isnull=False
        )
        
        # Si estamos editando, incluir el usuario actual
        if self.instance and self.instance.pk and self.instance.user:
            usuarios_profesional = usuarios_profesional | User.objects.filter(id=self.instance.user.id)
        
        self.fields['user'].queryset = usuarios_profesional.distinct()
        
        # ✅ Mostrar nombre del profesional vinculado (si existe)
        def label_usuario(obj):
            if hasattr(obj, 'perfil') and obj.perfil.profesional:
                return f"{obj.username} - {obj.perfil.profesional.nombre_completo}"
            return f"{obj.username} - {obj.get_full_name() or 'Disponible'}"
        
        self.fields['user'].label_from_instance = label_usuario
        
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
        
    class Meta:
        model = Profesional
        fields = ['foto', 'nombre', 'apellido', 'especialidad', 'telefono', 'email', 
                  'servicios', 'sucursales', 'activo', 'user']
        widgets = {
            'foto': forms.FileInput(attrs={
                'class': 'w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-green-50 file:text-green-700 hover:file:bg-green-100',
                'accept': 'image/*',
                'id': 'id_foto'
            }),
            'nombre': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-green-400 text-sm font-bold',
                'placeholder': 'Ej: Juan',
                'id': 'id_nombre'
            }),
            'apellido': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-green-400 text-sm font-bold',
                'placeholder': 'Ej: Pérez',
                'id': 'id_apellido'
            }),
            'especialidad': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-green-400 text-sm font-bold',
                'placeholder': 'Ej: Terapia del Lenguaje',
                'id': 'id_especialidad'
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 text-sm font-bold',
                'placeholder': '7XXXXXXX',
                'id': 'id_telefono'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 text-sm font-bold',
                'placeholder': 'correo@ejemplo.com',
                'id': 'id_email'
            }),
            'servicios': forms.CheckboxSelectMultiple(attrs={
                'class': 'space-y-2'
            }),
            'sucursales': forms.CheckboxSelectMultiple(attrs={
                'class': 'space-y-2'
            }),
            'activo': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-green-600 border-gray-300 rounded focus:ring-green-500',
                'id': 'id_activo'
            }),
            'user': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-purple-400 text-sm font-bold',
                'id': 'id_user'
            }),
        }