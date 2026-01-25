from django import forms
from .models import TipoServicio, Sucursal

class SucursalForm(forms.ModelForm):
    """Formulario para crear/editar sucursales"""
    
    class Meta:
        model = Sucursal
        fields = ['nombre', 'direccion', 'telefono', 'email', 'activa']
        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-cyan-400 text-sm font-bold',
                'placeholder': 'Ej: Sede Central'
            }),
            'direccion': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-cyan-400 text-sm font-bold',
                'placeholder': 'Av. Principal #123, La Paz'
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 text-sm font-bold',
                'placeholder': '2-1234567'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 text-sm font-bold',
                'placeholder': 'sucursal@centromisael.com'
            }),
            'activa': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-green-600 border-gray-300 rounded focus:ring-green-500'
            }),
        }
        labels = {
            'nombre': 'Nombre de la Sucursal',
            'direccion': 'Dirección',
            'telefono': 'Teléfono',
            'email': 'Email',
            'activa': 'Sucursal Activa',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Teléfono y email son opcionales
        self.fields['telefono'].required = False
        self.fields['email'].required = False

class TipoServicioForm(forms.ModelForm):
    class Meta:
        model = TipoServicio
        fields = ['nombre', 'descripcion', 'duracion_minutos', 'costo_base', 'precio_mensual', 'precio_proyecto', 'color', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-purple-400 text-sm font-bold',
                'placeholder': 'Ej: Terapia de Lenguaje'
            }),
            'descripcion': forms.Textarea(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-purple-400 text-sm font-bold',
                'rows': 3,
                'placeholder': 'Descripción del servicio...'
            }),
            'duracion_minutos': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 text-sm font-bold',
                'placeholder': '60',
                'min': '1'
            }),
            'costo_base': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 text-sm font-bold',
                'placeholder': '0.00',
                'step': '0.01',
                'min': '0'
            }),
            'precio_mensual': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-emerald-400 text-sm font-bold',
                'placeholder': '0.00',
                'step': '0.01',
                'min': '0'
            }),
            'precio_proyecto': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-amber-400 text-sm font-bold',
                'placeholder': '0.00',
                'step': '0.01',
                'min': '0'
            }),
            'color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'cursor-pointer',
                'style': 'width: 60px; height: 40px; border-radius: 8px; border: 2px solid #e5e7eb;'
            }),
            'activo': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-green-600 border-gray-300 rounded focus:ring-green-500'
            }),
        }
        labels = {
            'nombre': 'Nombre del Servicio',
            'descripcion': 'Descripción',
            'duracion_minutos': 'Duración (minutos)',
            'costo_base': 'Costo por Sesión (Bs.)',
            'precio_mensual': 'Precio Mensual Sugerido (Bs.)',
            'precio_proyecto': 'Precio Proyecto/Evaluación (Bs.)',
            'color': 'Color',
            'activo': 'Servicio Activo',
        }
        help_texts = {
            'costo_base': 'Costo base por sesión individual',
            'precio_mensual': 'Precio sugerido para mensualidades (opcional)',
            'precio_proyecto': 'Precio para proyecto o evaluación (opcional)',
            'color': 'Color para identificar en el calendario',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Precio mensual es opcional
        self.fields['precio_mensual'].required = False
        self.fields['precio_proyecto'].required = False