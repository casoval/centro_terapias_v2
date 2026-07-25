from django import forms
from django.contrib.auth.models import User

from .models import ArchivoCentro, CategoriaArchivo, ArchivoRolPermitido, ROL_CHOICES

_INPUT_CLASS = 'w-full rounded-lg border-slate-300 focus:ring-indigo-500 focus:border-indigo-500'


class ArchivoCentroForm(forms.ModelForm):
    """
    Formulario de subida/edición básica. El campo `visibilidad` se limita
    a las dos opciones simples ('Solo yo' / 'Todos en el centro') salvo
    que el usuario sea admin, quien puede elegir cualquier opción
    directamente (incluidas roles/usuarios, que luego se afinan en la
    pantalla de "Gestionar permisos").
    """

    class Meta:
        model = ArchivoCentro
        fields = ['titulo', 'descripcion', 'categoria', 'archivo', 'visibilidad']
        widgets = {
            'titulo': forms.TextInput(attrs={
                'class': _INPUT_CLASS,
                'placeholder': 'Ej: Protocolo de bioseguridad 2026',
            }),
            'descripcion': forms.Textarea(attrs={
                'class': _INPUT_CLASS, 'rows': 2, 'placeholder': 'Opcional',
            }),
            'categoria': forms.Select(attrs={'class': _INPUT_CLASS}),
            'archivo': forms.ClearableFileInput(attrs={
                'class': 'absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10',
                'id': 'id_archivo',
            }),
            'visibilidad': forms.RadioSelect,
        }

    def __init__(self, *args, es_admin=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categoria'].required = False
        self.fields['categoria'].queryset = CategoriaArchivo.objects.all()
        self.fields['categoria'].empty_label = 'Sin categoría'

        if es_admin:
            self.fields['visibilidad'].choices = ArchivoCentro.VISIBILIDAD_CHOICES
        else:
            self.fields['visibilidad'].choices = ArchivoCentro.VISIBILIDAD_SIMPLE_CHOICES
            # Si por algún motivo el valor guardado es 'roles'/'usuarios' y edita
            # un usuario no-admin, no lo forzamos a cambiarlo salvo que lo toque.


class CategoriaArchivoForm(forms.ModelForm):
    class Meta:
        model = CategoriaArchivo
        fields = ['nombre', 'descripcion']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': _INPUT_CLASS, 'placeholder': 'Ej: Recursos Humanos'}),
            'descripcion': forms.TextInput(attrs={'class': _INPUT_CLASS, 'placeholder': 'Opcional'}),
        }


class PermisosArchivoForm(forms.Form):
    """
    Formulario exclusivo de admin: ajusta la visibilidad completa de
    CUALQUIER archivo, incluyendo roles específicos y/o usuarios
    específicos con acceso.
    """
    visibilidad = forms.ChoiceField(
        choices=ArchivoCentro.VISIBILIDAD_CHOICES,
        widget=forms.RadioSelect,
    )
    roles = forms.MultipleChoiceField(
        choices=ROL_CHOICES, required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    usuarios = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(), required=False,
        widget=forms.SelectMultiple(attrs={'class': _INPUT_CLASS, 'size': 8}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo tiene sentido dar acceso explícito a usuarios de staff del centro
        self.fields['usuarios'].queryset = User.objects.filter(
            is_active=True,
        ).filter(
            models_q_staff()
        ).distinct().order_by('first_name', 'username')


def models_q_staff():
    """Q object: superusuarios o perfil con rol staff (evita import circular arriba)."""
    from django.db.models import Q
    return Q(is_superuser=True) | Q(perfil__rol__in=['profesional', 'recepcionista', 'gerente'])
