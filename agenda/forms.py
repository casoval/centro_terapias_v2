from django import forms
from .models import PermisoEdicionSesion


class PermisoEdicionForm(forms.ModelForm):
    class Meta:
        model = PermisoEdicionSesion
        fields = [
            'profesional',
            'fecha_sesion_desde',
            'fecha_sesion_hasta',
            'valido_desde',
            'valido_hasta',
            'puede_editar_estado',
            'puede_editar_notas',
            'puede_editar_otros_campos',
            'motivo',
        ]
        widgets = {
            'fecha_sesion_desde': forms.DateInput(
                attrs={'type': 'date'},
                format='%Y-%m-%d'
            ),
            'fecha_sesion_hasta': forms.DateInput(
                attrs={'type': 'date'},
                format='%Y-%m-%d'
            ),
            'valido_desde': forms.DateTimeInput(
                attrs={'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M'
            ),
            'valido_hasta': forms.DateTimeInput(
                attrs={'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M'
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Formatos para parseo correcto de los datetime-local
        self.fields['valido_desde'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M']
        self.fields['valido_hasta'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M']

    def clean(self):
        cleaned = super().clean()
        desde_sesion = cleaned.get('fecha_sesion_desde')
        hasta_sesion = cleaned.get('fecha_sesion_hasta')
        valido_desde = cleaned.get('valido_desde')
        valido_hasta = cleaned.get('valido_hasta')

        if desde_sesion and hasta_sesion and desde_sesion > hasta_sesion:
            raise forms.ValidationError(
                "La fecha 'Sesiones desde' no puede ser posterior a 'Sesiones hasta'."
            )
        if valido_desde and valido_hasta and valido_desde >= valido_hasta:
            raise forms.ValidationError(
                "La fecha 'Válido hasta' debe ser posterior a 'Válido desde'."
            )
        return cleaned