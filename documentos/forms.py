from django import forms
from .models import DocumentoPaciente, PlanTrabajo


class DocumentoPacienteForm(forms.ModelForm):
    """
    Formulario genérico de subida. `proyecto` y `mensualidad` se restringen
    al queryset del paciente en la vista (para no poder elegir uno de otro
    paciente), y normalmente llegan pre-seleccionados y ocultos según desde
    dónde se abra el formulario (ficha de proyecto, de mensualidad o del
    paciente en general).
    """

    class Meta:
        model = DocumentoPaciente
        # compartir_misael_kids ya no se ofrece acá: los planes de trabajo
        # para Misael Kids ahora se crean con su propio formulario dedicado
        # (PlanTrabajoForm), no mezclados con documentos generales/proyecto/
        # mensualidad. El campo se mantiene en el modelo por compatibilidad
        # histórica, pero ya no se completa desde este formulario.
        fields = ['titulo', 'descripcion', 'archivo', 'proyecto', 'mensualidad']
        widgets = {
            'titulo': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border-slate-300 focus:ring-indigo-500',
                'placeholder': 'Ej: Informe de evaluación inicial',
            }),
            'descripcion': forms.Textarea(attrs={
                'class': 'w-full rounded-lg border-slate-300 focus:ring-indigo-500',
                'rows': 2,
                'placeholder': 'Opcional',
            }),
            'archivo': forms.ClearableFileInput(attrs={
                'class': 'absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10',
                'id': 'id_archivo',
            }),
            'proyecto': forms.Select(attrs={'class': 'w-full rounded-lg border-slate-300'}),
            'mensualidad': forms.Select(attrs={'class': 'w-full rounded-lg border-slate-300'}),
        }

    def __init__(self, *args, paciente=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.paciente = paciente
        self.fields['proyecto'].required = False
        self.fields['mensualidad'].required = False
        if paciente is not None:
            self.fields['proyecto'].queryset = paciente.proyectos.all()
            self.fields['mensualidad'].queryset = paciente.mensualidades.all()
        else:
            self.fields['proyecto'].queryset = self.fields['proyecto'].queryset.none()
            self.fields['mensualidad'].queryset = self.fields['mensualidad'].queryset.none()

    def clean(self):
        cleaned = super().clean()
        proyecto = cleaned.get('proyecto')
        mensualidad = cleaned.get('mensualidad')
        if proyecto and mensualidad:
            raise forms.ValidationError(
                'Elige solo un destino: Proyecto o Mensualidad, no ambos.'
            )
        return cleaned


class PlanTrabajoForm(forms.ModelForm):
    """
    Formulario del plan de trabajo. El paciente NUNCA se elige acá (llega
    fijo desde la URL/vista, el niño ya está vinculado). Todos los campos
    de contenido del plan se llenan siempre a mano por el profesional —
    nada se autocompleta salvo el nombre, que solo se ofrece editable si
    quien sube el plan no es el propio profesional (ver __init__).
    """

    class Meta:
        model = PlanTrabajo
        fields = [
            'nombre_profesional_manual', 'telefono', 'area_intervencion',
            'frecuencia_sesiones', 'fecha_inicio', 'fecha_fin', 'proxima_revision',
            'descripcion', 'notas_seguimiento', 'archivo', 'activo',
        ]
        widgets = {
            'nombre_profesional_manual': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border-slate-300 focus:ring-indigo-500',
                'placeholder': 'Nombre del profesional que atiende (si no es tu cuenta)',
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border-slate-300 focus:ring-indigo-500',
                'placeholder': 'Opcional',
            }),
            'area_intervencion': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border-slate-300 focus:ring-indigo-500',
                'placeholder': 'Ej: Lenguaje, Terapia ocupacional, Psicología...',
            }),
            'frecuencia_sesiones': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border-slate-300 focus:ring-indigo-500',
                'placeholder': 'Ej: 2 veces por semana',
            }),
            'fecha_inicio': forms.DateInput(attrs={
                'type': 'date', 'class': 'w-full rounded-lg border-slate-300 focus:ring-indigo-500',
            }),
            'fecha_fin': forms.DateInput(attrs={
                'type': 'date', 'class': 'w-full rounded-lg border-slate-300 focus:ring-indigo-500',
            }),
            'proxima_revision': forms.DateInput(attrs={
                'type': 'date', 'class': 'w-full rounded-lg border-slate-300 focus:ring-indigo-500',
            }),
            'descripcion': forms.Textarea(attrs={
                'class': 'w-full rounded-lg border-slate-300 focus:ring-indigo-500', 'rows': 3,
                'placeholder': 'Objetivos y lineamientos del plan',
            }),
            'notas_seguimiento': forms.Textarea(attrs={
                'class': 'w-full rounded-lg border-slate-300 focus:ring-indigo-500', 'rows': 2,
                'placeholder': 'Opcional: avances, ajustes acordados...',
            }),
            'archivo': forms.ClearableFileInput(attrs={'class': 'w-full'}),
            'activo': forms.CheckboxInput(attrs={
                'class': 'rounded border-slate-300 text-indigo-600 focus:ring-indigo-500',
            }),
        }

    def __init__(self, *args, es_profesional_autor=False, **kwargs):
        """
        `es_profesional_autor`: True cuando quien está logueado es el
        profesional (rol 'profesional'). En ese caso su nombre se toma
        directo de `profesional.get_full_name()` y el campo manual queda
        oculto/no requerido. Si lo sube gerente/admin, el campo queda
        visible y editable para que completen el nombre a mano.
        """
        super().__init__(*args, **kwargs)
        self.fields['nombre_profesional_manual'].required = not es_profesional_autor
        if es_profesional_autor:
            self.fields['nombre_profesional_manual'].widget = forms.HiddenInput()
        else:
            self.fields['nombre_profesional_manual'].label = 'Nombre del profesional *'
