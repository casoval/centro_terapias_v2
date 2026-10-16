import datetime
from decimal import Decimal

from django import forms
from django.utils import timezone
from django.forms import BaseInlineFormSet, inlineformset_factory
from .personal import profesionales_activos
from .models import (
    ZonaAsistencia, PlantillaHorario, BloqueHorario, ConfigAsistencia,
    FechaEspecial, BloqueFechaEspecial, PermisoAsistencia, RegistroAsistencia,
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

    # No es un campo del modelo: la vista decide si edita en el lugar o crea una versión nueva.
    vigente_desde = forms.DateField(
        label='Aplicar desde',
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'class': INPUT, 'type': 'date'}),
        help_text='Los días anteriores a esta fecha conservan el horario que regía.',
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
        self.initial.setdefault('vigente_desde', timezone.localdate())

    def clean_dias(self):
        # Orden de semana estable (LUN..DOM) sin importar como llegaron
        dias = self.cleaned_data['dias']
        return [d for d in DIAS_SEMANA_ORDEN if d in dias]

    def clean(self):
        cleaned = super().clean()
        dias = set(cleaned.get('dias') or [])
        desde = cleaned.get('vigente_desde')
        inst = self.instance
        if dias and desde and inst.zona_id:
            # rango que ocuparía el horario editado: desde la fecha elegida hasta el fin de esta versión
            hasta_nuevo = inst.vigente_hasta if inst.pk else None
            otras = PlantillaHorario.objects.filter(zona_id=inst.zona_id, user_id=inst.user_id)
            if inst.pk:
                otras = otras.exclude(pk=inst.pk)
            nombres = dict(DIAS_CHOICES)
            for otra in otras:
                se_cruzan = ((hasta_nuevo is None or otra.vigente_desde <= hasta_nuevo)
                             and (otra.vigente_hasta is None or desde <= otra.vigente_hasta))
                comunes = [d for d in DIAS_SEMANA_ORDEN if d in dias and d in (otra.dias or [])]
                if comunes and se_cruzan:
                    cuando = f" ({otra.vigencia_texto})" if otra.vigencia_texto else ''
                    raise forms.ValidationError(
                        f"{', '.join(nombres[d] for d in comunes)} ya está en el horario "
                        f"«{otra.nombre or otra.dias_display}»{cuando} en esas fechas. "
                        "Quita esos días de uno de los dos o cambia la fecha."
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
        fields = ['hora_entrada', 'hora_salida', 'tolerancia_minutos', 'max_retraso_minutos']
        widgets = {
            'hora_entrada': forms.TimeInput(format=TIME_FMT, attrs={'class': TIME, 'type': 'time'}),
            'hora_salida': forms.TimeInput(format=TIME_FMT, attrs={'class': TIME, 'type': 'time'}),
            'tolerancia_minutos': forms.NumberInput(attrs={'class': INPUT, 'min': '0', 'max': '120'}),
            'max_retraso_minutos': forms.NumberInput(attrs={
                'class': INPUT, 'min': '0', 'max': '600', 'placeholder': 'sin límite'}),
        }
        labels = {'hora_entrada': 'Entrada', 'hora_salida': 'Salida',
                  'tolerancia_minutos': 'Tolerancia (min)',
                  'max_retraso_minutos': 'Límite para marcar (min)'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tolerancia_minutos'].initial = 10
        self.fields['max_retraso_minutos'].required = False


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
    aplicar_desde = forms.DateField(
        required=False, label='Aplicar el cambio de horario propio desde',
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'class': INPUT, 'type': 'date'}),
        help_text='Solo cuenta al activar o desactivar «Horario propio». Los días anteriores conservan el horario que regía.',
    )

    class Meta:
        model = ConfigAsistencia
        fields = ['user', 'zona', 'personalizado', 'device_id']
        # (aplicar_desde se declara abajo: no es un campo del modelo)
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
        self.fields['user'].queryset = profesionales_activos().order_by('last_name', 'first_name')
        self.fields['device_id'].required = False
        self.initial.setdefault('aplicar_desde', timezone.localdate())


class FechaEspecialForm(forms.ModelForm):
    class Meta:
        model = FechaEspecial
        fields = ['zona', 'fecha', 'tipo_horario', 'motivo', 'profesionales']
        widgets = {
            'zona':         forms.Select(attrs={'class': INPUT}),
            'fecha':        forms.DateInput(attrs={'class': INPUT, 'type': 'date'}, format='%Y-%m-%d'),
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
        self.fields['profesionales'].queryset = profesionales_activos().order_by('last_name', 'first_name')
        self.fields['profesionales'].required = False
        self.fields['motivo'].required = False


class PermisoReenrolamientoForm(forms.Form):
    enrolamiento_id = forms.IntegerField(widget=forms.HiddenInput())
    motivo = forms.CharField(
        label='Motivo del desbloqueo',
        widget=forms.TextInput(attrs={'class': INPUT,
            'placeholder': 'Ej: Problema con iluminación en consulta'})
    )


MESES_CHOICES = [(1, 'Enero'), (2, 'Febrero'), (3, 'Marzo'), (4, 'Abril'), (5, 'Mayo'), (6, 'Junio'),
                 (7, 'Julio'), (8, 'Agosto'), (9, 'Septiembre'), (10, 'Octubre'), (11, 'Noviembre'), (12, 'Diciembre')]


def primer_dia_mes_siguiente(hoy=None):
    hoy = hoy or timezone.localdate()
    return (hoy.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)


# Valores sugeridos cuando todavía no hay reglas guardadas: (hasta minutos, días de descuento) y días para el resto.
TRAMOS_SUGERIDOS = [(30, 0), (45, 0.5), (60, 1), (90, 2)]
DIAS_RESTO_SUGERIDO = 3


class ReglasAsistenciaForm(forms.Form):
    """Una nueva versión de las reglas que rige desde el día 1 del mes elegido (no es retroactiva)."""
    mes = forms.TypedChoiceField(choices=MESES_CHOICES, coerce=int, label='Aplicar desde el mes de',
                                 widget=forms.Select(attrs={'class': INPUT}))
    anio = forms.TypedChoiceField(choices=[], coerce=int, label='del año',
                                  widget=forms.Select(attrs={'class': INPUT}))
    dias_resto = forms.DecimalField(
        min_value=0, max_digits=4, decimal_places=2, label='Más allá del último tope',
        widget=forms.NumberInput(attrs={'class': INPUT, 'min': '0', 'step': '0.5'}),
        help_text='Días de descuento cuando el retraso supera el último tope, sin importar cuánto.',
    )

    hereda = forms.BooleanField(
        required=False, label='Terminar esta excepción: desde ese mes se usa la regla más general',
        widget=forms.CheckboxInput(attrs={'class': CHECK}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        hoy = timezone.localdate()
        self.fields['anio'].choices = [(a, str(a)) for a in range(2024, hoy.year + 3)]
        siguiente = primer_dia_mes_siguiente(hoy)
        self.initial.setdefault('mes', siguiente.month)
        self.initial.setdefault('anio', siguiente.year)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('mes') and cleaned.get('anio'):
            cleaned['vigente_desde'] = datetime.date(cleaned['anio'], cleaned['mes'], 1)
        return cleaned


class TramoForm(forms.Form):
    hasta = forms.DecimalField(
        required=False, min_value=0, max_digits=6, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': INPUT, 'min': '0', 'step': '0.01', 'placeholder': 'minutos'}))
    dias = forms.DecimalField(
        required=False, min_value=0, max_digits=4, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': INPUT, 'min': '0', 'step': '0.5', 'placeholder': 'días'}))


class BaseTramoFormSet(forms.BaseFormSet):
    """Filas «hasta N minutos -> X días»: topes crecientes y descuentos que no bajan. Filas vacías se ignoran."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        filas = []
        for form in self.forms:
            h, d = form.cleaned_data.get('hasta'), form.cleaned_data.get('dias')
            if h is None and d is None:
                continue
            if h is None or d is None:
                raise forms.ValidationError('Cada fila necesita los dos datos: hasta cuántos minutos y cuántos días.')
            filas.append((h, d))
        topes = [h for h, _d in filas]
        if len(set(topes)) != len(topes):
            raise forms.ValidationError('No repitas el mismo tope de minutos en dos filas.')
        filas.sort()
        for (h1, d1), (h2, d2) in zip(filas, filas[1:]):
            if d2 < d1:
                raise forms.ValidationError(
                    f'Hasta {h2} min no puede descontar menos ({d2} días) que hasta {h1} min ({d1} días).')
        self.filas_validas = filas


TramoFormSet = forms.formset_factory(TramoForm, formset=BaseTramoFormSet, extra=2, max_num=10, validate_max=True)


class PermisoAsistenciaForm(forms.ModelForm):
    """Datos del justificativo (quién, qué día y qué bloque vienen de la fila que se justifica)."""
    class Meta:
        model = PermisoAsistencia
        fields = ['tipo', 'detalle', 'comprobante']
        widgets = {
            'tipo': forms.Select(attrs={'class': INPUT}),
            'detalle': forms.Textarea(attrs={'class': INPUT, 'rows': 2,
                                             'placeholder': 'Ej: Certificado médico del Dr. Pérez, reposo 2 días'}),
        }
        labels = {'tipo': 'Tipo de justificativo', 'detalle': 'Detalle del justificativo escrito',
                  'comprobante': 'Comprobante (opcional)'}

    def clean_detalle(self):
        detalle = (self.cleaned_data.get('detalle') or '').strip()
        if len(detalle) < 5:
            raise forms.ValidationError('Describe el justificativo que se presentó.')
        return detalle


# ── Asuetos ──────────────────────────────────────────────────────────────────

class OtorgarAsuetoForm(forms.Form):
    """Otorga un derecho de asueto a un grupo de profesionales."""
    DESTINOS = [('todos', 'Todo el personal'), ('sucursal', 'Una o varias sucursales'),
                ('zona', 'Una o varias zonas'), ('elegidos', 'Profesionales elegidos')]
    motivo = forms.CharField(max_length=200, label='Motivo',
                             widget=forms.TextInput(attrs={'class': INPUT, 'placeholder': 'Ej: Día de la Mujer, Cumpleaños, Vacaciones'}))
    duracion = forms.ChoiceField(
        choices=[('0.5', 'Medio día'), ('1', 'Día completo'), ('varios', 'Varios días')], label='Duración',
        widget=forms.Select(attrs={'class': INPUT}))
    dias_varios = forms.DecimalField(
        required=False, min_value=1, max_digits=4, decimal_places=2, label='¿Cuántos días?',
        widget=forms.NumberInput(attrs={'class': INPUT, 'min': '1', 'step': '0.5'}))
    otorgado_el = forms.DateField(label='Fecha del evento / otorgamiento', widget=forms.DateInput(
        format='%Y-%m-%d', attrs={'class': INPUT, 'type': 'date'}))
    vence_el = forms.DateField(required=False, label='Vence el (opcional)', widget=forms.DateInput(
        format='%Y-%m-%d', attrs={'class': INPUT, 'type': 'date'}),
        help_text='Vacío = usa el plazo del tipo, o no vence.')
    destino = forms.ChoiceField(choices=DESTINOS, label='¿A quiénes?', widget=forms.Select(attrs={'class': INPUT}))
    sucursales = forms.ModelMultipleChoiceField(queryset=None, required=False, label='Sucursales')
    zonas = forms.ModelMultipleChoiceField(queryset=None, required=False, label='Zonas')
    profesionales = forms.ModelMultipleChoiceField(queryset=None, required=False, label='Profesionales')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth.models import User as DjangoUser
        from servicios.models import Sucursal
        self.fields['sucursales'].queryset = Sucursal.objects.all().order_by('nombre')
        self.fields['zonas'].queryset = ZonaAsistencia.objects.filter(activa=True).order_by('nombre')
        self.fields['profesionales'].queryset = profesionales_activos().order_by('last_name', 'first_name')
        self.fields['profesionales'].label_from_instance = lambda u: u.get_full_name() or u.username
        for f in ('sucursales', 'zonas', 'profesionales'):
            self.fields[f].widget = forms.SelectMultiple(attrs={'class': INPUT, 'size': '5'})
        self.initial.setdefault('otorgado_el', timezone.localdate())

    def clean(self):
        c = super().clean()
        if c.get('duracion') == 'varios':
            if not c.get('dias_varios'):
                self.add_error('dias_varios', 'Indica cuántos días.')
            c['dias'] = c.get('dias_varios')
        elif c.get('duracion'):
            c['dias'] = Decimal(c['duracion'])
        destino = c.get('destino')
        if destino == 'sucursal' and not c.get('sucursales'):
            self.add_error('sucursales', 'Elige al menos una sucursal.')
        if destino == 'zona' and not c.get('zonas'):
            self.add_error('zonas', 'Elige al menos una zona.')
        if destino == 'elegidos' and not c.get('profesionales'):
            self.add_error('profesionales', 'Elige al menos un profesional.')
        return c


class UsarAsuetoForm(forms.Form):
    """Registra la fecha (y bloque) en la que un profesional toma su asueto."""
    derecho = forms.ModelChoiceField(queryset=None, label='Asueto a usar', widget=forms.Select(attrs={'class': INPUT}))
    fecha = forms.DateField(label='Fecha en que lo toma', widget=forms.DateInput(
        format='%Y-%m-%d', attrs={'class': INPUT, 'type': 'date'}))
    bloque = forms.ChoiceField(
        choices=[('', 'Todo el día'), ('1', 'Solo el bloque 1 (mañana)'), ('2', 'Solo el bloque 2 (tarde)'),
                 ('3', 'Solo el bloque 3 (si el horario tiene 3 turnos)'),
                 ('4', 'Solo el bloque 4 (si el horario tiene 4 turnos)')],
        required=False, label='Qué parte', widget=forms.Select(attrs={'class': INPUT}))
    nota = forms.CharField(max_length=200, required=False, label='Nota (opcional)',
                           widget=forms.TextInput(attrs={'class': INPUT}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import DerechoAsueto
        hoy = timezone.localdate()
        disponibles = [d.pk for d in DerechoAsueto.objects.select_related('user').prefetch_related('usos')
                       if d.estado(hoy) == 'disponible']
        self.fields['derecho'].queryset = (DerechoAsueto.objects.filter(pk__in=disponibles)
                                           .select_related('user').prefetch_related('usos')
                                           .order_by('user__last_name', 'user__first_name'))
        self.fields['derecho'].label_from_instance = lambda d: (
            f"{d.user.get_full_name() or d.user.username} — {d.motivo} (saldo {d.saldo:g} d)")
