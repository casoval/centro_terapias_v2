from django import forms
from django.contrib.auth.models import User
from .models import PerfilUsuario

class UsuarioForm(forms.ModelForm):
    """Formulario para crear/editar usuarios"""
    
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 text-sm font-bold',
            'placeholder': '••••••••'
        }),
        label='Contraseña',
        required=False,
        help_text='Dejar en blanco para no cambiar la contraseña (solo al editar)'
    )
    
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 text-sm font-bold',
            'placeholder': '••••••••'
        }),
        label='Confirmar Contraseña',
        required=False
    )
    
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'is_active', 'is_staff']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-purple-400 text-sm font-bold',
                'placeholder': 'nombre_usuario'
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-purple-400 text-sm font-bold',
                'placeholder': 'Juan'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-purple-400 text-sm font-bold',
                'placeholder': 'Pérez'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 text-sm font-bold',
                'placeholder': 'usuario@ejemplo.com'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-green-600 border-gray-300 rounded focus:ring-green-500'
            }),
            'is_staff': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'
            }),
        }
        labels = {
            'username': 'Nombre de Usuario',
            'first_name': 'Nombre',
            'last_name': 'Apellido',
            'email': 'Email',
            'is_active': 'Usuario Activo',
            'is_staff': 'Acceso al Admin',
        }
    
    def __init__(self, *args, **kwargs):
        self.instance_pk = kwargs.get('instance').pk if kwargs.get('instance') else None
        super().__init__(*args, **kwargs)
        
        # Si estamos editando, la contraseña no es obligatoria
        if self.instance_pk:
            self.fields['password'].required = False
            self.fields['password_confirm'].required = False
            self.fields['password'].help_text = 'Dejar en blanco para no cambiar la contraseña'
        else:
            # Al crear, la contraseña es obligatoria
            self.fields['password'].required = True
            self.fields['password_confirm'].required = True
        
        # Email no es obligatorio
        self.fields['email'].required = False
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        
        # Validar contraseña solo si se proporcionó
        if password or password_confirm:
            if password != password_confirm:
                raise forms.ValidationError('Las contraseñas no coinciden')
            
            if len(password) < 4:
                raise forms.ValidationError('La contraseña debe tener al menos 4 caracteres')
        
        # Si estamos creando un nuevo usuario, la contraseña es obligatoria
        if not self.instance_pk and not password:
            raise forms.ValidationError('La contraseña es obligatoria para nuevos usuarios')
        
        return cleaned_data
    
    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        
        # Establecer contraseña solo si se proporcionó
        if password:
            user.set_password(password)
        
        if commit:
            user.save()
        
        return user


class PerfilUsuarioForm(forms.ModelForm):
    """Formulario para el perfil del usuario (rol y vinculaciones)"""
    
    class Meta:
        model = PerfilUsuario
        fields = ['rol', 'profesional', 'paciente', 'sucursales', 'activo']
        widgets = {
            'rol': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-purple-400 text-sm font-bold'
            }),
            'profesional': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-green-400 text-sm font-bold'
            }),
            'paciente': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 text-sm font-bold'
            }),
            'sucursales': forms.CheckboxSelectMultiple(attrs={
                'class': 'space-y-2'
            }),
            'activo': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-green-600 border-gray-300 rounded focus:ring-green-500'
            }),
        }
        labels = {
            'rol': 'Rol del Usuario',
            'profesional': 'Vincular con Profesional',
            'paciente': 'Vincular con Paciente',
            'sucursales': 'Sucursales Asignadas',
            'activo': 'Perfil Activo',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Hacer campos opcionales
        self.fields['profesional'].required = False
        self.fields['paciente'].required = False
        self.fields['rol'].required = False
        
        # Agregar opción vacía
        self.fields['profesional'].empty_label = "Ninguno"
        self.fields['paciente'].empty_label = "Ninguno"
    
    def clean(self):
        cleaned_data = super().clean()
        rol = cleaned_data.get('rol')
        profesional = cleaned_data.get('profesional')
        paciente = cleaned_data.get('paciente')
        
        # Validar que no se vincule profesional y paciente al mismo tiempo
        if profesional and paciente:
            raise forms.ValidationError(
                'No puedes vincular un profesional y un paciente al mismo tiempo'
            )
        
        # Si se vincula un profesional, el rol debe ser profesional
        if profesional and rol != 'profesional':
            cleaned_data['rol'] = 'profesional'
        
        # Si se vincula un paciente, el rol debe ser paciente
        if paciente and rol != 'paciente':
            cleaned_data['rol'] = 'paciente'
        
        return cleaned_data


class UsuarioCompletoForm(forms.Form):
    """
    Formulario combinado para crear usuario + perfil en un solo paso
    """
    # Datos del usuario
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-purple-400 text-sm font-bold',
            'placeholder': 'nombre_usuario'
        }),
        label='Nombre de Usuario'
    )
    
    first_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-purple-400 text-sm font-bold',
            'placeholder': 'Juan'
        }),
        label='Nombre'
    )
    
    last_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-purple-400 text-sm font-bold',
            'placeholder': 'Pérez'
        }),
        label='Apellido'
    )
    
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 text-sm font-bold',
            'placeholder': 'usuario@ejemplo.com'
        }),
        label='Email'
    )
    
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 text-sm font-bold',
            'placeholder': '••••••••'
        }),
        label='Contraseña'
    )
    
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 text-sm font-bold',
            'placeholder': '••••••••'
        }),
        label='Confirmar Contraseña'
    )
    
    is_active = forms.BooleanField(
        initial=True,
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'w-5 h-5 text-green-600 border-gray-300 rounded focus:ring-green-500'
        }),
        label='Usuario Activo'
    )
    
    is_staff = forms.BooleanField(
        initial=False,
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'
        }),
        label='Acceso al Admin'
    )
    
    # Datos del perfil
    rol = forms.ChoiceField(
        choices=[('', '-- Seleccionar --')] + PerfilUsuario.ROL_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-purple-400 text-sm font-bold'
        }),
        label='Rol del Usuario'
    )
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        
        if password != password_confirm:
            raise forms.ValidationError('Las contraseñas no coinciden')
        
        if len(password) < 4:
            raise forms.ValidationError('La contraseña debe tener al menos 4 caracteres')
        
        return cleaned_data