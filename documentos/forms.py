from django import forms
from .models import DocumentoPaciente


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
        fields = ['titulo', 'descripcion', 'archivo', 'proyecto', 'mensualidad', 'compartir_misael_kids']
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
            'compartir_misael_kids': forms.CheckboxInput(attrs={
                'class': 'rounded border-slate-300 text-indigo-600 focus:ring-indigo-500',
            }),
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
