from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from .models import (
    ZonaAsistencia, PlantillaHorario, BloqueHorario, ConfigAsistencia,
    FechaEspecial, BloqueFechaEspecial, RegistroAsistencia,
    DIAS_SEMANA_ORDEN,
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
    # Precision (metros) reportada por el GPS del dispositivo
    precision   = forms.FloatField(widget=forms.HiddenInput(), required=False, min_value=0)
    # Descriptor facial: lista de 128 numeros generada en el navegador con face-api.js
    vector_facial = forms.JSONField(widget=forms.HiddenInput(), required=False)
    foto_base64 = forms.CharField(widget=forms.HiddenInput(), required=False)
    device_id   = forms.CharField(widget=forms.HiddenInput(), max_length=255, required=False)
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


MAX_BLOQUES = 4
TIME_FMT = '%H:%M'


class PlantillaHorarioForm(forms.ModelForm):
    """Grupo de dias + nombre. Los bloques (entrada/salida) van en el formset."""
    dias = forms.MultipleChoiceField(
        choices=DIAS_CHOICES, widget=forms.CheckboxSelectMultiple(),
        label='Días de la semana',
        error_messages={'required': 'Marca al menos un día.'},
    )

    class Meta:
        model = PlantillaHorario
        fields = ['nombre', 'dias']
        widgets = {'nombre': forms.TextInput(attrs={
            'class': INPUT, 'placeholder': 'Ej: Lunes a viernes, Sábados...'})}
        labels = {'nombre': 'Nombre (opcional)'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['nombre'].required = False
        if self.instance and self.instance.pk:
            self.initial['dias'] = self.instance.dias or []

    def clean_dias(self):
        # Orden de semana estable (LUN..DOM) sin importar como llegaron
        dias = self.cleaned_data['dias']
        return [d for d in DIAS_SEMANA_ORDEN if d in dias]

    def clean(self):
        cleaned = super().clean()
        dias = set(cleaned.get('dias') or [])
        inst = self.instance
        if dias and inst.zona_id:
            otras = PlantillaHorario.objects.filter(zona_id=inst.zona_id, user_id=inst.user_id)
            if inst.pk:
                otras = otras.exclude(pk=inst.pk)
            nombres = dict(DIAS_CHOICES)
            for otra in otras:
                comunes = [d for d in DIAS_SEMANA_ORDEN if d in dias and d in (otra.dias or [])]
                if comunes:
                    raise forms.ValidationError(
                        f"{', '.join(nombres[d] for d in comunes)} ya está en el horario "
                        f"«{otra.nombre or otra.dias_display}». Quita esos días de uno de los dos."
                    )
        return cleaned

    def save(self, commit=True):
        inst = super().save(commit=False)
        inst.dias = list(self.cleaned_data['dias'])
        if commit:
            inst.save()
        return inst


class BloqueForm(forms.ModelForm):
    class Meta:
        fields = ['hora_entrada', 'hora_salida', 'tolerancia_minutos']
        widgets = {
            'hora_entrada': forms.TimeInput(format=TIME_FMT, attrs={'class': TIME, 'type': 'time'}),
            'hora_salida': forms.TimeInput(format=TIME_FMT, attrs={'class': TIME, 'type': 'time'}),
            'tolerancia_minutos': forms.NumberInput(attrs={'class': INPUT, 'min': '0', 'max': '120'}),
        }
        labels = {'hora_entrada': 'Entrada', 'hora_salida': 'Salida', 'tolerancia_minutos': 'Tolerancia (min)'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tolerancia_minutos'].initial = 10


class BloqueHorarioForm(BloqueForm):
    class Meta(BloqueForm.Meta):
        model = BloqueHorario


class BloqueFechaEspecialForm(BloqueForm):
    class Meta(BloqueForm.Meta):
        model = BloqueFechaEspecial


class BaseBloqueFormSet(BaseInlineFormSet):
    """Exige al menos un bloque, sin solapes entre ellos, y numera por hora de entrada."""
    requiere_bloques = True

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        bloques = []
        for form in self.forms:
            if form.cleaned_data.get('DELETE') or not form.cleaned_data.get('hora_entrada'):
                continue
            bloques.append((form.cleaned_data['hora_entrada'], form.cleaned_data['hora_salida']))
        if not bloques and self.requiere_bloques:
            raise forms.ValidationError('Define al menos un bloque de trabajo (entrada y salida).')
        bloques.sort()
        for (e1, s1), (e2, s2) in zip(bloques, bloques[1:]):
            if e2 < s1:
                raise forms.ValidationError(
                    f'Los bloques {e1:%H:%M}–{s1:%H:%M} y {e2:%H:%M}–{s2:%H:%M} se solapan.')

    def save(self, commit=True):
        resultado = super().save(commit=commit)
        if commit:
            # numera por hora de entrada (1 = primero del dia)
            padre = getattr(self, 'instance')
            hijos = sorted(getattr(padre, 'bloques').all(), key=lambda b: (b.hora_entrada, b.hora_salida))
            for i, h in enumerate(hijos, start=1):
                if h.orden != i:
                    h.orden = i
                    h.save(update_fields=['orden'])
        return resultado


def bloque_formset(padre_model, bloque_model, form_class, instance=None, data=None, prefix='bloques',
                   requiere_bloques=True):
    """Formset de bloques con filas vacias suficientes para completar hasta 3."""
    existentes = instance.bloques.count() if instance is not None and instance.pk else 0
    extra = 0 if existentes >= MAX_BLOQUES else max(1, 3 - existentes)
    FS = inlineformset_factory(
        padre_model, bloque_model, form=form_class, formset=BaseBloqueFormSet,
        extra=extra, can_delete=True, max_num=MAX_BLOQUES, validate_max=True,
    )
    FS.requiere_bloques = requiere_bloques
    return FS(data=data, instance=instance, prefix=prefix)


class ConfigAsistenciaForm(forms.ModelForm):
    class Meta:
        model = ConfigAsistencia
        fields = ['user', 'zona', 'personalizado', 'device_id']
        widgets = {
            'user':  forms.Select(attrs={'class': INPUT}),
            'zona':  forms.Select(attrs={'class': INPUT}),
            'personalizado': forms.CheckboxInput(attrs={'class': CHECK}),
            'device_id': forms.TextInput(attrs={'class': INPUT}),
        }
        labels = {
            'user': 'Profesional', 'zona': 'Zona asignada',
            'personalizado': 'Horario propio (en vez del de la zona)',
            'device_id': 'Device ID del celular',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth.models import User as DjangoUser
        self.fields['user'].queryset = DjangoUser.objects.filter(
            perfil__rol='profesional', is_active=True
        ).order_by('last_name', 'first_name')
        self.fields['device_id'].required = False


class FechaEspecialForm(forms.ModelForm):
    class Meta:
        model = FechaEspecial
        fields = ['zona', 'fecha', 'tipo_horario', 'motivo', 'profesionales']
        widgets = {
            'zona':         forms.Select(attrs={'class': INPUT}),
            'fecha':        forms.DateInput(attrs={'class': INPUT, 'type': 'date'}),
            'tipo_horario': forms.Select(attrs={'class': INPUT,
                            'onchange': 'toggleHorarioEspecial(this.value)'}),
            'motivo':       forms.TextInput(attrs={'class': INPUT,
                            'placeholder': 'Ej: Feriado nacional, Evento especial...'}),
            'profesionales': forms.CheckboxSelectMultiple(),
        }
        labels = {
            'zona': 'Zona / sede', 'fecha': 'Fecha',
            'tipo_horario': 'Ese día',
            'motivo': 'Motivo',
            'profesionales': 'Aplicar solo a (vacío = todos)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth.models import User as DjangoUser
        self.fields['profesionales'].queryset = DjangoUser.objects.filter(
            perfil__rol='profesional', is_active=True
        ).order_by('last_name', 'first_name')
        self.fields['profesionales'].required = False
        self.fields['motivo'].required = False


class PermisoReenrolamientoForm(forms.Form):
    enrolamiento_id = forms.IntegerField(widget=forms.HiddenInput())
    motivo = forms.CharField(
        label='Motivo del desbloqueo',
        widget=forms.TextInput(attrs={'class': INPUT,
            'placeholder': 'Ej: Problema con iluminación en consulta'})
    )
