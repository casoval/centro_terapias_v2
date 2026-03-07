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
        self.fields['telefono'].required = False
        self.fields['email'].required = False


class TipoServicioForm(forms.ModelForm):
    class Meta:
        model = TipoServicio
        fields = [
            'nombre', 'descripcion', 'duracion_minutos',
            'costo_base', 'precio_mensual', 'precio_proyecto',
            'color', 'activo',
            # 🆕 Campos nuevos para servicio externo
            'es_servicio_externo', 'porcentaje_centro',
        ]
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
            # 🆕 Widgets para servicio externo
            'es_servicio_externo': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-purple-600 border-gray-300 rounded focus:ring-purple-500',
                'id': 'id_es_servicio_externo',
                # Al cambiar el checkbox, mostrar/ocultar el campo de porcentaje
                'onchange': 'togglePorcentajeCentro(this)',
            }),
            'porcentaje_centro': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-purple-400 text-sm font-bold',
                'placeholder': 'Ej: 10.00',
                'step': '0.01',
                'min': '0',
                'max': '100',
                'id': 'id_porcentaje_centro',
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
            # 🆕
            'es_servicio_externo': 'Servicio de Profesional Externo',
            'porcentaje_centro': '% que retiene el Centro',
        }
        help_texts = {
            'costo_base': 'Costo base por sesión individual',
            'precio_mensual': 'Precio sugerido para mensualidades (opcional)',
            'precio_proyecto': 'Precio para proyecto o evaluación (opcional)',
            'color': 'Color para identificar en el calendario',
            # 🆕
            'es_servicio_externo': 'El profesional cobra su propio precio; el centro retiene solo un porcentaje',
            'porcentaje_centro': 'Porcentaje del precio que queda en el centro (ej: 10 = 10%). Se puede ajustar al momento del pago.',
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['precio_mensual'].required = False
        self.fields['precio_proyecto'].required = False
        # 🆕 El porcentaje solo es obligatorio si es servicio externo (validado en el modelo)
        self.fields['porcentaje_centro'].required = False

    def clean(self):
        cleaned_data = super().clean()
        es_externo = cleaned_data.get('es_servicio_externo')
        porcentaje = cleaned_data.get('porcentaje_centro')

        if es_externo and not porcentaje:
            self.add_error(
                'porcentaje_centro',
                'Debe especificar el porcentaje del centro para servicios externos.'
            )
        return cleaned_data