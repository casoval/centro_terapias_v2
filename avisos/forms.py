from django import forms

from .models import Anuncio, TAMANO_MAX_MB


class AnuncioForm(forms.ModelForm):
    quitar_adjunto = forms.BooleanField(required=False, label='Quitar el archivo actual')

    class Meta:
        model = Anuncio
        fields = ['titulo', 'mensaje', 'adjunto', 'importancia',
                  'dest_gerentes', 'dest_recepcionistas', 'dest_profesionales', 'dest_pacientes',
                  'sucursales', 'fecha_inicio', 'fecha_fin', 'guardar_en_historial', 'pedir_confirmacion']
        widgets = {
            'mensaje': forms.Textarea(attrs={'rows': 4}),
            'fecha_inicio': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'fecha_fin': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'sucursales': forms.CheckboxSelectMultiple,
            'adjunto': forms.ClearableFileInput(attrs={'accept': '.jpg,.jpeg,.png,.webp,.pdf'}),
        }

    def clean(self):
        data = super().clean()
        ini, fin = data.get('fecha_inicio'), data.get('fecha_fin')
        if ini and fin and fin < ini:
            self.add_error('fecha_fin', 'La fecha final no puede ser anterior a la inicial.')
        if not any(data.get(c) for c in ('dest_gerentes', 'dest_recepcionistas', 'dest_profesionales', 'dest_pacientes')):
            raise forms.ValidationError('Elige al menos un destinatario.')
        tiene_adjunto = bool(data.get('adjunto')) and not data.get('quitar_adjunto')
        if not (data.get('mensaje') or '').strip() and not tiene_adjunto:
            raise forms.ValidationError('Escribe un mensaje o adjunta una imagen o PDF.')
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get('quitar_adjunto') and 'adjunto' not in self.files:
            obj.borrar_archivo()
            obj.adjunto = ''
        if commit:
            obj.save()
            self.save_m2m()
        return obj
