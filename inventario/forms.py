from django import forms
from django.contrib.auth.models import User

from .models import ItemInventario, CategoriaItemInventario, TransferenciaInventario

_INPUT_CLASS = 'w-full rounded-lg border-slate-300 focus:ring-indigo-500 focus:border-indigo-500'


class CategoriaItemForm(forms.ModelForm):
    class Meta:
        model = CategoriaItemInventario
        fields = ['nombre']
        widgets = {'nombre': forms.TextInput(attrs={'class': _INPUT_CLASS, 'placeholder': 'Ej: Material terapéutico'})}


class ItemInventarioForm(forms.ModelForm):
    class Meta:
        model = ItemInventario
        fields = ['nombre', 'descripcion', 'categoria', 'unidad', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': _INPUT_CLASS, 'placeholder': 'Ej: Pelotas sensoriales'}),
            'descripcion': forms.TextInput(attrs={'class': _INPUT_CLASS, 'placeholder': 'Opcional'}),
            'categoria': forms.Select(attrs={'class': _INPUT_CLASS}),
            'unidad': forms.Select(attrs={'class': _INPUT_CLASS}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categoria'].required = False
        self.fields['categoria'].empty_label = 'Sin categoría'


class AgregarStockForm(forms.Form):
    """Sumar cantidad al inventario de un titular. `titular` se restringe en la vista a las opciones permitidas."""
    titular = forms.ChoiceField(widget=forms.Select(attrs={'class': _INPUT_CLASS}))
    item = forms.ModelChoiceField(
        queryset=ItemInventario.objects.filter(activo=True),
        widget=forms.Select(attrs={'class': _INPUT_CLASS}),
    )
    cantidad = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={'class': _INPUT_CLASS}))
    motivo = forms.CharField(
        required=False, max_length=255,
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS, 'placeholder': 'Opcional: ej. "Compra mensual"'}),
    )

    def __init__(self, *args, titulares_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['titular'].choices = titulares_choices or []


class AjustarStockForm(forms.Form):
    """Exclusivo admin: fija el stock exacto de un ítem para un titular."""
    nueva_cantidad = forms.IntegerField(min_value=0, widget=forms.NumberInput(attrs={'class': _INPUT_CLASS}))
    motivo = forms.CharField(
        required=False, max_length=255,
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS, 'placeholder': 'Ej: "Conteo físico de inventario"'}),
    )


class SolicitarTransferenciaForm(forms.Form):
    """
    Cualquier usuario solicita mover stock desde un titular sobre el que
    tiene control. Nunca ejecuta el movimiento: solo queda 'pendiente'
    hasta que el admin la apruebe.
    """
    DESTINO_TIPO_CHOICES = [
        ('centro', 'Dejar en el Centro (para que el admin lo verifique)'),
        ('usuario', 'Transferir a otro profesional/usuario'),
    ]

    origen = forms.ChoiceField(widget=forms.Select(attrs={'class': _INPUT_CLASS}))
    item = forms.ModelChoiceField(
        queryset=ItemInventario.objects.filter(activo=True),
        widget=forms.Select(attrs={'class': _INPUT_CLASS}),
    )
    cantidad = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={'class': _INPUT_CLASS}))
    destino_tipo = forms.ChoiceField(choices=DESTINO_TIPO_CHOICES, widget=forms.RadioSelect, initial='centro')
    destino_usuario = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False,
        widget=forms.Select(attrs={'class': _INPUT_CLASS}),
    )
    motivo = forms.ChoiceField(choices=TransferenciaInventario.MOTIVO_CHOICES, widget=forms.Select(attrs={'class': _INPUT_CLASS}))
    notas_solicitante = forms.CharField(
        required=False, max_length=255,
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS, 'placeholder': 'Opcional'}),
    )

    def __init__(self, *args, origen_choices=None, usuario_actual=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['origen'].choices = origen_choices or []
        from django.db.models import Q
        qs = User.objects.filter(is_active=True).filter(
            Q(is_superuser=True) | Q(perfil__rol__in=['profesional', 'recepcionista', 'gerente'])
        )
        if usuario_actual is not None:
            qs = qs.exclude(id=usuario_actual.id)
        self.fields['destino_usuario'].queryset = qs.distinct().order_by('first_name', 'username')

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('destino_tipo') == 'usuario' and not cleaned.get('destino_usuario'):
            self.add_error('destino_usuario', 'Selecciona a quién transferir.')
        return cleaned


class ResolverTransferenciaForm(forms.Form):
    """Exclusivo admin: aprobar o rechazar, con notas opcionales."""
    ACCION_CHOICES = [('aprobar', 'Aprobar'), ('rechazar', 'Rechazar')]
    accion = forms.ChoiceField(choices=ACCION_CHOICES, widget=forms.RadioSelect)
    notas_admin = forms.CharField(
        required=False, max_length=255,
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS, 'placeholder': 'Opcional'}),
    )
