"""
marketing/forms.py

Formularios de la interfaz. No importa de servicios/profesionales: los
selectores de sede y profesional se alimentan desde `fuentes`.
"""

import os

from django import forms
from PIL import Image

from . import fuentes
from .models import REDES_CHOICES, Activo, Campana, ConfigMarketing, FichaContenido, Marca
from .proveedores.registro import listar_proveedores_texto

CLASE_INPUT = ('w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-800 '
               'focus:border-fuchsia-500 focus:ring-2 focus:ring-fuchsia-200 focus:outline-none bg-white')
CLASE_CHECK = 'h-4 w-4 rounded border-slate-300 text-fuchsia-600 focus:ring-fuchsia-400'


class EstiloMixin:
    """Aplica las clases de Tailwind a todos los campos."""

    def _estilizar(self):
        for nombre, campo in self.fields.items():
            w = campo.widget
            if isinstance(w, (forms.CheckboxInput,)):
                w.attrs['class'] = CLASE_CHECK
            elif isinstance(w, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                w.attrs['class'] = CLASE_CHECK
            elif isinstance(w, forms.ClearableFileInput):
                w.attrs['class'] = 'block w-full text-sm text-slate-600'
            else:
                w.attrs['class'] = CLASE_INPUT
            if isinstance(w, forms.Textarea):
                w.attrs.setdefault('rows', 3)


# ── Campaña ─────────────────────────────────────────────────────────────────

LINEAMIENTOS_CAMPOS = [
    ('publico', 'Público objetivo', 'Ej: madres y padres de niños de 2 a 6 años en Potosí'),
    ('estilo_visual', 'Estilo visual', 'Ej: cálido, luminoso, colores pastel, cercano'),
    ('paleta', 'Paleta de colores', 'Ej: azul y amarillo del logo'),
    ('mostrar', 'Debe mostrar', 'Ej: la sala de terapia, juguetes, el logo al final'),
    ('evitar', 'Debe evitar', 'Ej: caras de niños, comparaciones con otros centros'),
    ('llamada_accion', 'Llamada a la acción', 'Ej: Agenda tu evaluación por WhatsApp'),
]


class CampanaForm(EstiloMixin, forms.ModelForm):
    redes = forms.MultipleChoiceField(
        choices=REDES_CHOICES, required=False, widget=forms.CheckboxSelectMultiple, label='Redes destino',
    )
    sucursal_id = forms.ChoiceField(required=False, label='Sede (opcional)')
    profesional_id = forms.ChoiceField(required=False, label='Profesional destacado (opcional)')

    class Meta:
        model = Campana
        fields = ['marca', 'titulo', 'objetivo', 'estado', 'origen_visual', 'quien_escribe',
                  'fichas', 'activos_referencia', 'notas']
        widgets = {
            'fichas': forms.CheckboxSelectMultiple,
            'activos_referencia': forms.CheckboxSelectMultiple,
            'notas': forms.Textarea(attrs={'rows': 2}),
        }
        labels = {
            'titulo': 'Título de la campaña', 'objetivo': 'Objetivo', 'estado': 'Estado',
            'origen_visual': 'Origen visual', 'quien_escribe': '¿Quién escribe el texto?',
            'fichas': 'Fichas de contenido (solo aprobadas)', 'activos_referencia': 'Fotos / videos de referencia',
            'notas': 'Notas internas',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['marca'].queryset = Marca.objects.filter(activa=True)
        seleccionadas = self.instance.fichas.values_list('pk', flat=True) if self.instance.pk else []
        qs = FichaContenido.objects.filter(activa=True).select_related('marca')
        self.fields['fichas'].queryset = (
            qs.filter(aprobada=True) | qs.filter(pk__in=list(seleccionadas))
        ).distinct().order_by('marca__nombre', 'titulo')
        self.fields['fichas'].label_from_instance = (
            lambda f: f'{f.titulo}' + ('' if f.aprobada else ' (SIN APROBAR)')
        )
        activos_sel = self.instance.activos_referencia.values_list('pk', flat=True) if self.instance.pk else []
        activos = Activo.objects.filter(activo=True).select_related('marca')
        self.fields['activos_referencia'].queryset = (
            activos.filter(pk__in=[a.pk for a in activos if a.usable_en_publicidad])
            | activos.filter(pk__in=list(activos_sel))
        ).distinct().order_by('marca__nombre', 'nombre')
        self.fields['activos_referencia'].label_from_instance = lambda a: f'{a.nombre} ({a.get_tipo_display()})'
        self.fields['fichas'].required = False
        self.fields['activos_referencia'].required = False

        self.fields['sucursal_id'].choices = [('', '— Todas / ninguna —')] + [
            (str(s['id']), s['nombre']) for s in fuentes.datos_sucursales()
        ]
        self.fields['profesional_id'].choices = [('', '— Ninguno —')] + [
            (str(p['id']), f'{p["nombre_completo"]} · {p["especialidad"]}') for p in fuentes.listar_profesionales()
        ]
        for clave, etiqueta, ayuda in LINEAMIENTOS_CAMPOS:
            self.fields[f'lin_{clave}'] = forms.CharField(
                required=False, label=etiqueta,
                widget=forms.Textarea(attrs={'rows': 2, 'placeholder': ayuda}),
            )

        if self.instance.pk:
            self.fields['redes'].initial = self.instance.redes
            self.fields['sucursal_id'].initial = str(self.instance.sucursal_id or '')
            self.fields['profesional_id'].initial = str(self.instance.profesional_id or '')
            for clave, _, _ in LINEAMIENTOS_CAMPOS:
                self.fields[f'lin_{clave}'].initial = (self.instance.lineamientos or {}).get(clave, '')
        else:
            self.fields['redes'].initial = ['instagram', 'facebook', 'tiktok']
        self._estilizar()

    def clean(self):
        datos = super().clean()
        marca = datos.get('marca')
        if marca:
            ajenas = [f.titulo for f in datos.get('fichas', []) if f.marca_id != marca.pk]
            if ajenas:
                self.add_error('fichas', f'Estas fichas son de otra marca: {", ".join(ajenas)}.')
            ajenos = [a.nombre for a in datos.get('activos_referencia', []) if a.marca_id != marca.pk]
            if ajenos:
                self.add_error('activos_referencia', f'Estos activos son de otra marca: {", ".join(ajenos)}.')
        return datos

    def save(self, commit=True):
        c = super().save(commit=False)
        c.redes = list(self.cleaned_data.get('redes') or [])
        c.sucursal_id = int(self.cleaned_data['sucursal_id']) if self.cleaned_data.get('sucursal_id') else None
        c.profesional_id = int(self.cleaned_data['profesional_id']) if self.cleaned_data.get('profesional_id') else None
        c.lineamientos = {
            k: self.cleaned_data.get(f'lin_{k}', '').strip()
            for k, _, _ in LINEAMIENTOS_CAMPOS if self.cleaned_data.get(f'lin_{k}', '').strip()
        }
        if commit:
            c.save()
            self.save_m2m()
        return c


class GenerarGuionForm(EstiloMixin, forms.Form):
    cantidad = forms.ChoiceField(choices=[('1', '1 guion'), ('2', '2 variantes'), ('3', '3 variantes')], label='Cuántos')
    proveedor = forms.ChoiceField(required=False, label='Modelo de IA')
    instrucciones_extra = forms.CharField(
        required=False, label='Indicaciones adicionales (opcional)',
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Ej: menciona que hay cupos esta semana'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['proveedor'].choices = [('', 'Automático (el configurado)')] + [
            (p['id'], p['nombre'] if p['disponible'] else f'{p["nombre"]} (falta {p["variable_entorno"]})')
            for p in listar_proveedores_texto()
        ]
        self._estilizar()


# ── Fichas, marcas, activos, configuración ──────────────────────────────────

class FichaForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = FichaContenido
        fields = ['marca', 'tipo', 'titulo', 'texto', 'activa']
        labels = {'titulo': 'Título', 'texto': 'Texto (lo único que la IA podrá afirmar)', 'activa': 'Activa'}
        widgets = {'texto': forms.Textarea(attrs={'rows': 12})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['marca'].queryset = Marca.objects.filter(activa=True)
        self._estilizar()


class MarcaForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = Marca
        fields = ['nombre', 'tono_voz', 'lineamientos_base', 'reglas_contenido', 'palabras_prohibidas',
                  'permite_precios', 'cierre_fijo', 'whatsapp', 'url_web', 'hashtags_base',
                  'color_primario', 'color_secundario', 'color_acento',
                  'cuenta_facebook', 'cuenta_instagram', 'cuenta_tiktok']
        labels = {
            'tono_voz': 'Tono de voz', 'lineamientos_base': 'Lineamientos visuales de la marca',
            'reglas_contenido': 'Reglas de contenido', 'palabras_prohibidas': 'Palabras prohibidas (una por línea)',
            'permite_precios': 'Se pueden mencionar precios', 'cierre_fijo': 'Cierre fijo',
            'hashtags_base': 'Hashtags base', 'color_primario': 'Color primario (#RRGGBB)',
            'color_secundario': 'Color secundario', 'color_acento': 'Color de acento',
            'cuenta_facebook': 'Cuenta de Facebook', 'cuenta_instagram': 'Cuenta de Instagram',
            'cuenta_tiktok': 'Cuenta de TikTok', 'url_web': 'Sitio web',
        }
        widgets = {
            'tono_voz': forms.Textarea(attrs={'rows': 3}),
            'lineamientos_base': forms.Textarea(attrs={'rows': 3}),
            'reglas_contenido': forms.Textarea(attrs={'rows': 4}),
            'palabras_prohibidas': forms.Textarea(attrs={'rows': 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._estilizar()


EXTENSIONES = {
    'imagen': {'.jpg', '.jpeg', '.png', '.webp'},
    'video': {'.mp4', '.mov', '.webm'},
    'audio': {'.mp3', '.wav', '.m4a', '.aac'},
}
MAX_MB = {'imagen': 10, 'video': 150, 'audio': 20}


class ActivoForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = Activo
        fields = ['marca', 'nombre', 'tipo', 'origen', 'archivo', 'descripcion', 'etiquetas',
                  'contiene_personas', 'contiene_menores', 'autorizacion_confirmada', 'autorizacion_nota']
        labels = {
            'contiene_personas': 'Aparecen personas', 'contiene_menores': 'Aparecen niños, niñas o adolescentes',
            'autorizacion_confirmada': 'Tengo autorización ESCRITA para usar esta imagen en publicidad',
            'autorizacion_nota': 'Dónde está archivada la autorización',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['marca'].queryset = Marca.objects.filter(activa=True)
        self._estilizar()

    def clean(self):
        datos = super().clean()
        archivo, tipo = datos.get('archivo'), datos.get('tipo')
        if archivo and tipo:
            ext = os.path.splitext(archivo.name)[1].lower()
            if ext not in EXTENSIONES[tipo]:
                self.add_error('archivo', f'Para "{tipo}" se aceptan: {", ".join(sorted(EXTENSIONES[tipo]))}.')
            elif archivo.size > MAX_MB[tipo] * 1024 * 1024:
                self.add_error('archivo', f'El archivo supera {MAX_MB[tipo]} MB.')
            elif tipo == 'imagen':
                try:
                    Image.open(archivo).verify()
                    archivo.seek(0)
                except Exception:
                    self.add_error('archivo', 'El archivo no es una imagen válida.')
        return datos


class ConfigForm(EstiloMixin, forms.ModelForm):
    proveedor_texto = forms.ChoiceField(required=False, label='Modelo de IA para guiones')

    class Meta:
        model = ConfigMarketing
        fields = ['proveedor_texto', 'presupuesto_mensual_usd', 'tope_por_pieza_usd', 'calidad_por_defecto',
                  'retencion_intermedios_dias', 'ia_permite_ninos_realistas']
        labels = {
            'presupuesto_mensual_usd': 'Presupuesto mensual en IA (USD)',
            'tope_por_pieza_usd': 'Tope por pieza (USD)',
            'calidad_por_defecto': 'Calidad por defecto',
            'retencion_intermedios_dias': 'Días que se conservan los archivos intermedios',
            'ia_permite_ninos_realistas': 'Permitir que la IA genere niños fotorrealistas (no recomendado)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['proveedor_texto'].choices = [('', 'Automático (el primero disponible)')] + [
            (p['id'], p['nombre'] if p['disponible'] else f'{p["nombre"]} (falta {p["variable_entorno"]})')
            for p in listar_proveedores_texto()
        ]
        self._estilizar()


class PiezaCrearForm(EstiloMixin, forms.Form):
    tipo = forms.ChoiceField(
        label='Qué crear',
        choices=[('carrusel', 'Carrusel (varias diapositivas)'), ('imagen', 'Imagen única')],
    )
    formato = forms.ChoiceField(
        label='Formato',
        choices=[
            ('4x5', 'Vertical 4:5 · feed de Instagram y Facebook'),
            ('9x16', 'Vertical 9:16 · Reels, TikTok e Historias'),
            ('1x1', 'Cuadrado 1:1'),
        ],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._estilizar()
