from django import forms
from django.contrib.auth.models import User

from .models import ArchivoCentro, CategoriaArchivo, ArchivoRolPermitido, ROL_CHOICES, ROLES_STAFF_CHOICES

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
            # Usamos FileInput (no ClearableFileInput) a propósito: al editar,
            # ClearableFileInput imprime su propio bloque "Currently / Clear /
            # Change" sin estilo, que no podemos maquetar. El archivo actual
            # se muestra aparte en el template y este input siempre se trata
            # como "elegir un archivo nuevo para reemplazar".
            'archivo': forms.FileInput(attrs={
                'class': 'absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10',
                'id': 'id_archivo',
            }),
            'visibilidad': forms.RadioSelect,
        }

    def __init__(self, *args, es_admin=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.es_admin = es_admin
        self.fields['categoria'].required = False
        self.fields['categoria'].queryset = CategoriaArchivo.objects.all()
        self.fields['categoria'].empty_label = 'Sin categoría'

        if es_admin:
            self.fields['visibilidad'].choices = ArchivoCentro.VISIBILIDAD_CHOICES

            # Solo el admin ve/usa estos dos campos extra (no son campos del
            # modelo ArchivoCentro: se guardan en ArchivoRolPermitido /
            # ArchivoUsuarioPermitido, ver ArchivoCentroForm.guardar_permisos_avanzados).
            self.fields['roles'] = forms.MultipleChoiceField(
                choices=ROLES_STAFF_CHOICES, required=False,
                widget=forms.CheckboxSelectMultiple,
                label='Roles con acceso',
            )
            self.fields['usuarios'] = forms.ModelMultipleChoiceField(
                queryset=User.objects.filter(is_active=True).filter(models_q_staff()).distinct().order_by('first_name', 'username'),
                required=False,
                widget=forms.SelectMultiple(attrs={'class': _INPUT_CLASS, 'size': 8}),
                label='Usuarios con acceso',
            )

            instancia = kwargs.get('instance')
            if instancia is not None and instancia.pk and not self.is_bound:
                self.fields['roles'].initial = list(
                    instancia.roles_permitidos.values_list('rol', flat=True)
                )
                self.fields['usuarios'].initial = list(
                    instancia.usuarios_permitidos.values_list('usuario_id', flat=True)
                )
        else:
            self.fields['visibilidad'].choices = ArchivoCentro.VISIBILIDAD_SIMPLE_CHOICES
            # Si por algún motivo el valor guardado es 'roles'/'usuarios' y edita
            # un usuario no-admin, no lo forzamos a cambiarlo salvo que lo toque.

    def guardar_permisos_avanzados(self, archivo):
        """
        Llamar SOLO cuando es_admin=True, después de form.save(). Sincroniza
        ArchivoRolPermitido / ArchivoUsuarioPermitido según lo elegido.
        """
        if not self.es_admin:
            return
        from .models import ArchivoRolPermitido, ArchivoUsuarioPermitido

        ArchivoRolPermitido.objects.filter(archivo=archivo).delete()
        if archivo.visibilidad == 'roles':
            ArchivoRolPermitido.objects.bulk_create([
                ArchivoRolPermitido(archivo=archivo, rol=rol)
                for rol in self.cleaned_data.get('roles', [])
            ])

        ArchivoUsuarioPermitido.objects.filter(archivo=archivo).delete()
        if archivo.visibilidad == 'usuarios':
            ArchivoUsuarioPermitido.objects.bulk_create([
                ArchivoUsuarioPermitido(archivo=archivo, usuario=usuario)
                for usuario in self.cleaned_data.get('usuarios', [])
            ])


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
        choices=ROLES_STAFF_CHOICES, required=False,
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
    """
    Q object: perfil con rol staff del centro (profesional, recepcionista,
    gerente). A propósito NO incluye is_superuser=True: el admin ya ve
    absolutamente todo sin importar la visibilidad del archivo, así que
    listarlo como "usuario específico" seleccionable es redundante y
    confuso (evita import circular arriba con este import diferido).
    """
    from django.db.models import Q
    return Q(perfil__rol__in=['profesional', 'recepcionista', 'gerente'])
