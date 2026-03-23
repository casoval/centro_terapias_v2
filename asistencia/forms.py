from django import forms
from django.utils import timezone
from .models import (
    ZonaAsistencia, HorarioPredeterminado, ConfigAsistencia,
    FechaEspecial, PermisoReenrolamiento, RegistroAsistencia
)

INPUT = 'w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 text-sm font-bold bg-white'
CHECK = 'w-5 h-5 text-blue-600 border-gray-300 rounded focus:ring-blue-500'
TIME  = f'{INPUT} text-center'

DIAS_CHOICES = [
    ('LUN','Lunes'), ('MAR','Martes'), ('MIE','Miércoles'),
    ('JUE','Jueves'), ('VIE','Viernes'), ('SAB','Sábado'), ('DOM','Domingo'),
]


class MarcarAsistenciaForm(forms.Form):
    tipo        = forms.ChoiceField(choices=[('ENTRADA','Entrada'),('SALIDA','Salida')], widget=forms.HiddenInput())
    latitud     = forms.DecimalField(max_digits=9, decimal_places=6, widget=forms.HiddenInput())
    longitud    = forms.DecimalField(max_digits=9, decimal_places=6, widget=forms.HiddenInput())
    vector_facial = forms.JSONField(widget=forms.HiddenInput(), required=False)
    foto_base64 = forms.CharField(widget=forms.HiddenInput(), required=False)
    device_id   = forms.CharField(widget=forms.HiddenInput(), max_length=255)
    observacion = forms.CharField(
        label='Observación (opcional)', required=False,
        widget=forms.Textarea(attrs={'class': INPUT, 'rows': 2,
            'placeholder': 'Ej: Llegué tarde por tráfico...', 'maxlength': 500})
    )


class EditarObservacionForm(forms.ModelForm):
    class Meta:
        model = RegistroAsistencia
        fields = ['observacion']
        widgets = {'observacion': forms.Textarea(attrs={'class': INPUT, 'rows': 3, 'maxlength': 500})}
        labels = {'observacion': 'Observación'}

    def clean(self):
        cleaned = super().clean()
        if self.instance and not self.instance.es_editable_hoy():
            raise forms.ValidationError("Solo puedes editar la observación durante el día del registro.")
        return cleaned


class ZonaAsistenciaForm(forms.ModelForm):
    class Meta:
        model = ZonaAsistencia
        fields = ['nombre', 'sucursal', 'latitud', 'longitud', 'radio_metros', 'activa']
        widgets = {
            'nombre':      forms.TextInput(attrs={'class': INPUT, 'placeholder': 'Ej: Sede Central'}),
            'sucursal':    forms.Select(attrs={'class': INPUT}),
            'latitud':     forms.NumberInput(attrs={'class': INPUT, 'step': 'any', 'id': 'id_latitud'}),
            'longitud':    forms.NumberInput(attrs={'class': INPUT, 'step': 'any', 'id': 'id_longitud'}),
            'radio_metros':forms.NumberInput(attrs={'class': INPUT, 'min': '10', 'max': '2000'}),
            'activa':      forms.CheckboxInput(attrs={'class': CHECK}),
        }
        labels = {
            'nombre': 'Nombre de la zona', 'sucursal': 'Sucursal de referencia (opcional)',
            'latitud': 'Latitud', 'longitud': 'Longitud',
            'radio_metros': 'Radio permitido (metros)', 'activa': 'Zona activa',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sucursal'].required = False
        self.fields['sucursal'].empty_label = "Sin sucursal vinculada"


class HorarioPredeterminadoForm(forms.ModelForm):
    dias_partido = forms.MultipleChoiceField(
        choices=DIAS_CHOICES, required=False,
        widget=forms.CheckboxSelectMultiple(),
        label='Días con horario partido',
        help_text='Ej: Lunes a Viernes'
    )
    dias_continuo = forms.MultipleChoiceField(
        choices=DIAS_CHOICES, required=False,
        widget=forms.CheckboxSelectMultiple(),
        label='Días con horario continuo',
        help_text='Ej: Sábado'
    )

    class Meta:
        model = HorarioPredeterminado
        fields = [
            'dias_partido', 'dias_continuo',
            'hora_entrada', 'hora_salida', 'tolerancia_minutos',
            'hora_entrada_tarde', 'hora_salida_tarde', 'tolerancia_tarde',
        ]
        widgets = {
            'hora_entrada':       forms.TimeInput(attrs={'class': TIME, 'type': 'time'}),
            'hora_salida':        forms.TimeInput(attrs={'class': TIME, 'type': 'time'}),
            'tolerancia_minutos': forms.NumberInput(attrs={'class': INPUT, 'min': '0', 'max': '120'}),
            'hora_entrada_tarde': forms.TimeInput(attrs={'class': TIME, 'type': 'time'}),
            'hora_salida_tarde':  forms.TimeInput(attrs={'class': TIME, 'type': 'time'}),
            'tolerancia_tarde':   forms.NumberInput(attrs={'class': INPUT, 'min': '0', 'max': '120'}),
        }
        labels = {
            'hora_entrada': 'Entrada mañana / continuo',
            'hora_salida':  'Salida mañana / continuo',
            'tolerancia_minutos': 'Tolerancia mañana (min)',
            'hora_entrada_tarde': 'Entrada tarde',
            'hora_salida_tarde':  'Salida tarde',
            'tolerancia_tarde':   'Tolerancia tarde (min)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial['dias_partido']  = self.instance.dias_partido or []
            self.initial['dias_continuo'] = self.instance.dias_continuo or []
        self.fields['hora_entrada_tarde'].required = False
        self.fields['hora_salida_tarde'].required  = False
        self.fields['tolerancia_tarde'].required   = False

    def clean(self):
        cleaned = super().clean()
        partido  = cleaned.get('dias_partido', [])
        continuo = cleaned.get('dias_continuo', [])
        overlap  = set(partido) & set(continuo)
        if overlap:
            raise forms.ValidationError(
                f"Los días {', '.join(overlap)} no pueden ser partido y continuo al mismo tiempo."
            )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.dias_partido  = list(self.cleaned_data.get('dias_partido', []))
        instance.dias_continuo = list(self.cleaned_data.get('dias_continuo', []))
        if commit:
            instance.save()
        return instance


class ConfigAsistenciaForm(forms.ModelForm):
    dias_partido_custom = forms.MultipleChoiceField(
        choices=DIAS_CHOICES, required=False,
        widget=forms.CheckboxSelectMultiple(),
        label='Días partido (sobreescribe zona)',
    )
    dias_continuo_custom = forms.MultipleChoiceField(
        choices=DIAS_CHOICES, required=False,
        widget=forms.CheckboxSelectMultiple(),
        label='Días continuo (sobreescribe zona)',
    )

    class Meta:
        model = ConfigAsistencia
        fields = [
            'user', 'zona', 'personalizado',
            'dias_partido_custom', 'dias_continuo_custom',
            'hora_entrada_custom', 'hora_salida_custom', 'tolerancia_custom',
            'hora_entrada_tarde_custom', 'hora_salida_tarde_custom', 'tolerancia_tarde_custom',
            'device_id',
        ]
        widgets = {
            'user':  forms.Select(attrs={'class': INPUT}),
            'zona':  forms.Select(attrs={'class': INPUT}),
            'personalizado': forms.CheckboxInput(attrs={'class': CHECK}),
            'hora_entrada_custom':       forms.TimeInput(attrs={'class': TIME, 'type': 'time'}),
            'hora_salida_custom':        forms.TimeInput(attrs={'class': TIME, 'type': 'time'}),
            'tolerancia_custom':         forms.NumberInput(attrs={'class': INPUT, 'min': '0'}),
            'hora_entrada_tarde_custom': forms.TimeInput(attrs={'class': TIME, 'type': 'time'}),
            'hora_salida_tarde_custom':  forms.TimeInput(attrs={'class': TIME, 'type': 'time'}),
            'tolerancia_tarde_custom':   forms.NumberInput(attrs={'class': INPUT, 'min': '0'}),
            'device_id': forms.TextInput(attrs={'class': INPUT}),
        }
        labels = {
            'user': 'Profesional', 'zona': 'Zona asignada',
            'personalizado': 'Activar personalización',
            'hora_entrada_custom': 'Entrada mañana personalizada',
            'hora_salida_custom':  'Salida mañana personalizada',
            'tolerancia_custom':   'Tolerancia mañana (min)',
            'hora_entrada_tarde_custom': 'Entrada tarde personalizada',
            'hora_salida_tarde_custom':  'Salida tarde personalizada',
            'tolerancia_tarde_custom':   'Tolerancia tarde (min)',
            'device_id': 'Device ID del celular',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth.models import User as DjangoUser
        self.fields['user'].queryset = DjangoUser.objects.filter(
            perfil__rol='profesional', is_active=True
        ).order_by('last_name', 'first_name')
        if self.instance and self.instance.pk:
            self.initial['dias_partido_custom']  = self.instance.dias_partido_custom or []
            self.initial['dias_continuo_custom'] = self.instance.dias_continuo_custom or []
        for f in ['hora_entrada_custom','hora_salida_custom','tolerancia_custom',
                  'hora_entrada_tarde_custom','hora_salida_tarde_custom',
                  'tolerancia_tarde_custom','device_id']:
            self.fields[f].required = False
        self.fields['dias_partido_custom'].required  = False
        self.fields['dias_continuo_custom'].required = False

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.personalizado:
            p = self.cleaned_data.get('dias_partido_custom', [])
            c = self.cleaned_data.get('dias_continuo_custom', [])
            instance.dias_partido_custom  = list(p) if p else None
            instance.dias_continuo_custom = list(c) if c else None
        if commit:
            instance.save()
        return instance


class FechaEspecialForm(forms.ModelForm):
    class Meta:
        model = FechaEspecial
        fields = [
            'zona', 'fecha', 'tipo_horario', 'motivo', 'profesionales',
            'hora_entrada_especial', 'hora_salida_especial', 'tolerancia_especial',
            'hora_entrada_tarde_especial', 'hora_salida_tarde_especial', 'tolerancia_tarde_especial',
        ]
        widgets = {
            'zona':         forms.Select(attrs={'class': INPUT}),
            'fecha':        forms.DateInput(attrs={'class': INPUT, 'type': 'date'}),
            'tipo_horario': forms.Select(attrs={'class': INPUT,
                            'onchange': 'toggleHorarioEspecial(this.value)'}),
            'motivo':       forms.TextInput(attrs={'class': INPUT,
                            'placeholder': 'Ej: Feriado nacional, Evento especial...'}),
            'profesionales':forms.CheckboxSelectMultiple(),
            'hora_entrada_especial':       forms.TimeInput(attrs={'class': TIME, 'type': 'time'}),
            'hora_salida_especial':        forms.TimeInput(attrs={'class': TIME, 'type': 'time'}),
            'tolerancia_especial':         forms.NumberInput(attrs={'class': INPUT, 'min': '0', 'max': '120'}),
            'hora_entrada_tarde_especial': forms.TimeInput(attrs={'class': TIME, 'type': 'time'}),
            'hora_salida_tarde_especial':  forms.TimeInput(attrs={'class': TIME, 'type': 'time'}),
            'tolerancia_tarde_especial':   forms.NumberInput(attrs={'class': INPUT, 'min': '0', 'max': '120'}),
        }
        labels = {
            'zona': 'Zona / sede', 'fecha': 'Fecha',
            'tipo_horario': 'Tipo de horario ese día',
            'motivo': 'Motivo',
            'profesionales': 'Aplicar solo a (vacío = todos)',
            'hora_entrada_especial': 'Entrada',
            'hora_salida_especial':  'Salida',
            'tolerancia_especial':   'Tolerancia (min)',
            'hora_entrada_tarde_especial': 'Entrada tarde',
            'hora_salida_tarde_especial':  'Salida tarde',
            'tolerancia_tarde_especial':   'Tolerancia tarde (min)',
        }
        help_texts = {
            'hora_entrada_especial': 'Dejar vacío para usar el horario base de la zona',
            'hora_entrada_tarde_especial': 'Solo si el tipo es partido',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth.models import User as DjangoUser
        self.fields['profesionales'].queryset = DjangoUser.objects.filter(
            perfil__rol='profesional', is_active=True
        ).order_by('last_name', 'first_name')
        for f in ['profesionales', 'motivo', 'hora_entrada_especial', 'hora_salida_especial',
                  'tolerancia_especial', 'hora_entrada_tarde_especial',
                  'hora_salida_tarde_especial', 'tolerancia_tarde_especial']:
            self.fields[f].required = False


class PermisoReenrolamientoForm(forms.Form):
    enrolamiento_id = forms.IntegerField(widget=forms.HiddenInput())
    motivo = forms.CharField(
        label='Motivo del desbloqueo',
        widget=forms.TextInput(attrs={'class': INPUT,
            'placeholder': 'Ej: Problema con iluminación en consulta'})
    )
