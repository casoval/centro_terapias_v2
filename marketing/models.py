"""
marketing/models.py

App INDEPENDIENTE de publicidad. No usa pacientes, agenda, facturación,
sesiones ni chat. Solo LEE (con ForeignKey opcionales, on_delete=SET_NULL)
de: servicios.TipoServicio, servicios.Sucursal y profesionales.Profesional.
Todo acceso de lectura a esos datos pasa por `marketing/fuentes.py`
(paso siguiente); aquí solo se referencian por string para no importar nada.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from .storage_backends import get_marketing_storage

REDES_CHOICES = [
    ('facebook', 'Facebook'),
    ('instagram', 'Instagram'),
    ('tiktok', 'TikTok'),
    ('otra', 'Otra'),
]

FORMATO_CHOICES = [
    ('9x16', 'Vertical 9:16 (Reels, TikTok, Historias)'),
    ('4x5', 'Vertical 4:5 (feed Instagram/Facebook)'),
    ('1x1', 'Cuadrado 1:1'),
    ('16x9', 'Horizontal 16:9'),
]

# Dimensiones de salida en píxeles (ancho, alto) por formato
DIMENSIONES_FORMATO = {
    '9x16': (1080, 1920),
    '4x5': (1080, 1350),
    '1x1': (1080, 1080),
    '16x9': (1920, 1080),
}


def _validar_color_hex(valor):
    if valor and (len(valor) != 7 or not valor.startswith('#')):
        raise ValidationError('Usa el formato #RRGGBB (ej: #3B82F6).')
    if valor:
        try:
            int(valor[1:], 16)
        except ValueError:
            raise ValidationError('Usa el formato #RRGGBB (ej: #3B82F6).')


# ══════════════════════════════════════════════════════════════════════════
# MARCA
# ══════════════════════════════════════════════════════════════════════════

class Marca(models.Model):
    """Identidad visual y de voz. Hay 3: Centro Misael, Misael Kids, Misael Toys."""

    slug = models.SlugField(max_length=50, unique=True)
    nombre = models.CharField(max_length=100)
    activa = models.BooleanField(default=True)

    logo = models.ImageField(
        upload_to='marcas/', storage=get_marketing_storage, blank=True, null=True,
    )
    color_primario = models.CharField(max_length=7, blank=True, validators=[_validar_color_hex])
    color_secundario = models.CharField(max_length=7, blank=True, validators=[_validar_color_hex])
    color_acento = models.CharField(max_length=7, blank=True, validators=[_validar_color_hex])

    tono_voz = models.TextField(
        blank=True,
        help_text='Cómo habla la marca. Ej: cálido, cercano, trata de "tú", sin tecnicismos.',
    )
    lineamientos_base = models.TextField(
        blank=True,
        help_text='Lineamientos visuales y creativos que aplican SIEMPRE a esta marca.',
    )
    reglas_contenido = models.TextField(
        blank=True,
        help_text='Reglas de qué se puede y no se puede afirmar (ej: no prometer curas).',
    )
    palabras_prohibidas = models.TextField(
        blank=True,
        help_text='Una por línea. Si un guion las contiene, se marca como no válido.',
    )
    permite_precios = models.BooleanField(
        default=False,
        help_text='Si está desactivado, los guiones no pueden mencionar precios.',
    )

    cierre_fijo = models.CharField(
        max_length=255, blank=True,
        help_text='Frase o datos de cierre. Ej: "Agenda tu evaluación por WhatsApp".',
    )
    whatsapp = models.CharField(max_length=20, blank=True)
    url_web = models.URLField(blank=True)
    hashtags_base = models.CharField(max_length=500, blank=True, help_text='Separados por espacio.')
    cuenta_facebook = models.CharField(max_length=100, blank=True)
    cuenta_instagram = models.CharField(max_length=100, blank=True)
    cuenta_tiktok = models.CharField(max_length=100, blank=True)

    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Marca'
        verbose_name_plural = 'Marcas'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

    @property
    def lista_palabras_prohibidas(self):
        return [p.strip().lower() for p in self.palabras_prohibidas.splitlines() if p.strip()]


# ══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN GLOBAL (una sola fila)
# ══════════════════════════════════════════════════════════════════════════

class ConfigMarketing(models.Model):
    """Ajustes editables desde el admin (patrón de agente.ConfigAgente). Una sola fila."""

    # Proveedor elegido por capacidad. Vacío = el primero disponible.
    proveedor_texto = models.CharField(max_length=50, blank=True)
    proveedor_imagen = models.CharField(max_length=50, blank=True)
    proveedor_video = models.CharField(max_length=50, blank=True)
    proveedor_voz = models.CharField(max_length=50, blank=True)

    presupuesto_mensual_usd = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal('20.00'),
        help_text='Tope de gasto en IA por mes calendario (USD). 0 = sin generación con IA de pago.',
    )
    tope_por_pieza_usd = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal('5.00'),
        help_text='Una pieza cuyo costo estimado supere esto no se genera sin confirmación.',
    )
    calidad_por_defecto = models.CharField(
        max_length=10, default='borrador',
        choices=[('borrador', 'Borrador (barato)'), ('final', 'Final (calidad alta)')],
    )
    retencion_intermedios_dias = models.PositiveIntegerField(
        default=30,
        help_text='Días que se conservan clips y borradores intermedios tras aprobar una pieza.',
    )
    ia_permite_ninos_realistas = models.BooleanField(
        default=False,
        help_text='Si está apagado, la IA solo puede generar niños en estilo ilustración/3D/personaje, '
                  'nunca fotorrealistas.',
    )
    tarifas = models.JSONField(
        default=dict, blank=True,
        help_text='Tabla editable de precios por proveedor (USD). Los precios cambian; actualízala aquí.',
    )

    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuración de Marketing'
        verbose_name_plural = 'Configuración de Marketing'

    def __str__(self):
        return 'Configuración de Marketing'

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton
        # `objects.create()` fuerza INSERT; con una fila ya existente eso
        # chocaría. Se permite INSERT o UPDATE según corresponda.
        kwargs.pop('force_insert', None)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # no se puede borrar

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


# ══════════════════════════════════════════════════════════════════════════
# BIBLIOTECA DE ACTIVOS (fotos/videos propios usados como referencia)
# ══════════════════════════════════════════════════════════════════════════

class Activo(models.Model):
    TIPO_CHOICES = [('imagen', 'Imagen'), ('video', 'Video'), ('audio', 'Audio / música')]
    ORIGEN_CHOICES = [
        ('instalaciones', 'Instalaciones / sede'),
        ('equipo', 'Equipo / profesionales'),
        ('producto', 'Producto (Misael Toys)'),
        ('evento', 'Evento'),
        ('ilustracion', 'Ilustración / diseño'),
        ('ia_generado', 'Generado con IA'),
        ('otro', 'Otro'),
    ]

    marca = models.ForeignKey(Marca, on_delete=models.PROTECT, related_name='activos')
    nombre = models.CharField(max_length=150)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='imagen')
    origen = models.CharField(max_length=20, choices=ORIGEN_CHOICES, default='otro')
    archivo = models.FileField(upload_to='activos/%Y/%m/', storage=get_marketing_storage)
    descripcion = models.CharField(max_length=300, blank=True)
    etiquetas = models.CharField(max_length=300, blank=True, help_text='Separadas por coma.')

    # ── Control de imagen de personas (consentimiento) ──────────────────────
    contiene_personas = models.BooleanField(default=False)
    contiene_menores = models.BooleanField(
        default=False,
        help_text='Marca si aparece cualquier niño/niña/adolescente.',
    )
    autorizacion_confirmada = models.BooleanField(
        default=False,
        help_text='Hay autorización ESCRITA para usar esta imagen en publicidad '
                  '(de los tutores si hay menores; de la persona si es adulta).',
    )
    autorizacion_nota = models.CharField(
        max_length=300, blank=True,
        help_text='Dónde está la autorización (ej: "carpeta Autorizaciones 2026, ficha 14").',
    )

    profesional = models.ForeignKey(
        'profesionales.Profesional', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
        help_text='Solo si el activo es una foto de un profesional concreto.',
    )

    activo = models.BooleanField(default=True)
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Activo'
        verbose_name_plural = 'Activos'
        ordering = ['-creado']
        indexes = [models.Index(fields=['marca', 'tipo', 'activo'])]

    def __str__(self):
        return f'{self.nombre} ({self.marca})'

    def clean(self):
        # Coherencia: menores implica personas
        if self.contiene_menores:
            self.contiene_personas = True
        # Con menores, la autorización debe estar respaldada por una referencia
        if self.contiene_menores and self.autorizacion_confirmada and not self.autorizacion_nota.strip():
            raise ValidationError({
                'autorizacion_nota': 'Con menores, indica dónde está archivada la autorización escrita.',
            })

    @property
    def usable_en_publicidad(self):
        """
        Reglas de consentimiento:
          - Sin personas: usable.
          - Con personas adultas: requiere autorización confirmada.
          - Con menores: requiere autorización confirmada Y la referencia de dónde está.
        """
        if not self.activo:
            return False
        if not (self.contiene_personas or self.contiene_menores):
            return True
        if not self.autorizacion_confirmada:
            return False
        if self.contiene_menores and not self.autorizacion_nota.strip():
            return False
        return True


# ══════════════════════════════════════════════════════════════════════════
# BASE DE CONOCIMIENTO POR MARCA
# ══════════════════════════════════════════════════════════════════════════

class FichaContenido(models.Model):
    """
    Texto aprobado que el guion PUEDE usar. El generador de guiones solo ve
    fichas aprobadas: nunca inventa datos fuera de ellas.
    """
    TIPO_CHOICES = [
        ('servicio', 'Servicio'),
        ('producto', 'Producto'),
        ('programa', 'Programa / nivel educativo'),
        ('evento', 'Evento'),
        ('promocion', 'Promoción'),
        ('faq', 'Pregunta frecuente'),
        ('institucional', 'Institucional'),
    ]
    FUENTE_CHOICES = [
        ('manual', 'Escrita a mano'),
        ('servicios_data', 'Sincronizada desde las páginas públicas (core.servicios_data)'),
        ('tipo_servicio', 'Sincronizada desde TipoServicio'),
        ('sucursales', 'Sincronizada desde las sucursales'),
    ]

    marca = models.ForeignKey(Marca, on_delete=models.CASCADE, related_name='fichas')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='servicio')
    titulo = models.CharField(max_length=200)
    texto = models.TextField(help_text='Contenido aprobado. Es lo ÚNICO que el guion puede afirmar.')

    fuente = models.CharField(max_length=20, choices=FUENTE_CHOICES, default='manual')
    clave_fuente = models.CharField(
        max_length=200, blank=True,
        help_text='Identificador en la fuente (ej: el slug del servicio). Evita duplicados al sincronizar.',
    )

    huella_fuente = models.CharField(
        max_length=64, blank=True, editable=False,
        help_text='Hash del texto tal como lo entregó la última sincronización. Permite detectar '
                  'si la ficha fue editada a mano (y entonces no sobrescribirla).',
    )

    aprobada = models.BooleanField(default=False)
    aprobada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    aprobada_en = models.DateTimeField(null=True, blank=True)
    activa = models.BooleanField(default=True)

    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Ficha de contenido'
        verbose_name_plural = 'Fichas de contenido'
        ordering = ['marca', 'tipo', 'titulo']
        constraints = [
            models.UniqueConstraint(
                fields=['marca', 'fuente', 'clave_fuente'],
                condition=~models.Q(clave_fuente=''),
                name='ficha_unica_por_fuente',
            ),
        ]

    def __str__(self):
        return f'[{self.marca}] {self.titulo}'


# ══════════════════════════════════════════════════════════════════════════
# CAMPAÑA
# ══════════════════════════════════════════════════════════════════════════

class Campana(models.Model):
    OBJETIVO_CHOICES = [
        ('captar', 'Captar consultas / evaluaciones / inscripciones'),
        ('servicio', 'Dar a conocer un servicio o producto'),
        ('educar', 'Educar / informar'),
        ('evento', 'Promocionar un evento o fecha'),
        ('promocion', 'Promoción u oferta'),
        ('marca', 'Reforzar la marca'),
    ]
    ESTADO_CHOICES = [
        ('borrador', 'Borrador'),
        ('en_curso', 'En curso'),
        ('completada', 'Completada'),
        ('archivada', 'Archivada'),
    ]
    ORIGEN_VISUAL_CHOICES = [
        ('propias', 'Con mis fotos (se usan tal cual)'),
        ('referencia', 'Inspirado en mis fotos de referencia'),
        ('ia_total', 'La IA crea todo'),
    ]
    QUIEN_ESCRIBE_CHOICES = [
        ('usuario', 'Yo escribo el texto'),
        ('ia', 'La IA escribe'),
        ('ia_editable', 'La IA propone y yo edito'),
    ]

    marca = models.ForeignKey(Marca, on_delete=models.PROTECT, related_name='campanas')
    titulo = models.CharField(max_length=200)
    objetivo = models.CharField(max_length=20, choices=OBJETIVO_CHOICES, default='servicio')
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='borrador')

    origen_visual = models.CharField(max_length=12, choices=ORIGEN_VISUAL_CHOICES, default='propias')
    quien_escribe = models.CharField(max_length=12, choices=QUIEN_ESCRIBE_CHOICES, default='ia_editable')
    lineamientos = models.JSONField(
        default=dict, blank=True,
        help_text='Estructura libre: público, tono, estilo visual, paleta, qué mostrar, qué evitar, '
                  'duración, llamada a la acción.',
    )
    redes = models.JSONField(default=list, blank=True, help_text='Lista de redes destino.')

    # Fuentes de contenido (lectura de otras apps; todas opcionales)
    fichas = models.ManyToManyField(FichaContenido, blank=True, related_name='campanas')
    servicio = models.ForeignKey(
        'servicios.TipoServicio', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    sucursal = models.ForeignKey(
        'servicios.Sucursal', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    profesional = models.ForeignKey(
        'profesionales.Profesional', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    activos_referencia = models.ManyToManyField(Activo, blank=True, related_name='campanas')

    notas = models.TextField(blank=True)
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Campaña'
        verbose_name_plural = 'Campañas'
        ordering = ['-creada']
        indexes = [models.Index(fields=['marca', 'estado'])]

    def __str__(self):
        return f'{self.titulo} ({self.marca})'

    def clean(self):
        validas = {r for r, _ in REDES_CHOICES}
        if not isinstance(self.redes, list) or any(r not in validas for r in self.redes):
            raise ValidationError({'redes': f'Redes válidas: {", ".join(sorted(validas))}.'})


# ══════════════════════════════════════════════════════════════════════════
# GUION
# ══════════════════════════════════════════════════════════════════════════

class Guion(models.Model):
    ESTADO_CHOICES = [
        ('borrador', 'Borrador'),
        ('rechazado', 'Rechazado por validación'),
        ('validado', 'Validado'),
        ('aprobado', 'Aprobado'),
    ]
    GENERADO_POR_CHOICES = [('usuario', 'Usuario'), ('ia', 'IA')]

    campana = models.ForeignKey(Campana, on_delete=models.CASCADE, related_name='guiones')
    version = models.PositiveIntegerField(default=1)
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='borrador')

    gancho = models.CharField(max_length=300, blank=True, help_text='Primeros 3 segundos / titular.')
    escenas = models.JSONField(
        default=list, blank=True,
        help_text='Lista de {texto_pantalla, locucion, prompt_visual, duracion_seg}.',
    )
    caption = models.TextField(blank=True)
    hashtags = models.CharField(max_length=500, blank=True)

    # Instantánea de los datos usados (para que cambiar un precio después
    # no altere el historial de lo que se generó).
    datos_fuente = models.JSONField(default=dict, blank=True)
    validacion = models.JSONField(default=dict, blank=True, help_text='Resultado del validador de contenido.')

    generado_por = models.CharField(max_length=10, choices=GENERADO_POR_CHOICES, default='usuario')
    proveedor_texto = models.CharField(max_length=50, blank=True)
    modelo_texto = models.CharField(max_length=100, blank=True)

    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Guion'
        verbose_name_plural = 'Guiones'
        ordering = ['campana', '-version']
        constraints = [
            models.UniqueConstraint(fields=['campana', 'version'], name='guion_version_unica'),
        ]

    def __str__(self):
        return f'Guion v{self.version} - {self.campana.titulo}'


# ══════════════════════════════════════════════════════════════════════════
# PIEZA (video, imagen o carrusel) Y SUS ELEMENTOS
# ══════════════════════════════════════════════════════════════════════════

class Pieza(models.Model):
    TIPO_CHOICES = [('video', 'Video'), ('imagen', 'Imagen'), ('carrusel', 'Carrusel')]
    MODO_CHOICES = [
        ('plantilla', 'Plantilla (Pillow, sin IA)'),
        ('presentacion', 'Presentación con fotos (ffmpeg, sin IA)'),
        ('ia_imagen', 'Imagen generada/editada con IA'),
        ('ia_video', 'Video generado con IA'),
        ('mixto', 'Mixto'),
    ]
    CALIDAD_CHOICES = [('borrador', 'Borrador'), ('final', 'Final')]
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('generando', 'Generando'),
        ('ensamblando', 'Ensamblando'),
        ('listo', 'Listo para revisar'),
        ('aprobado', 'Aprobado'),
        ('publicada', 'Publicada'),
        ('fallida', 'Fallida'),
        ('cancelada', 'Cancelada'),
    ]

    campana = models.ForeignKey(Campana, on_delete=models.CASCADE, related_name='piezas')
    guion = models.ForeignKey(Guion, on_delete=models.SET_NULL, null=True, blank=True, related_name='piezas')

    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='video')
    formato = models.CharField(max_length=5, choices=FORMATO_CHOICES, default='9x16')
    modo = models.CharField(max_length=15, choices=MODO_CHOICES, default='presentacion')
    calidad = models.CharField(max_length=10, choices=CALIDAD_CHOICES, default='borrador')
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='pendiente')

    proveedor_imagen = models.CharField(max_length=50, blank=True)
    proveedor_video = models.CharField(max_length=50, blank=True)
    proveedor_voz = models.CharField(max_length=50, blank=True)

    archivo_final = models.FileField(upload_to='piezas/%Y/%m/', storage=get_marketing_storage, blank=True)
    miniatura = models.ImageField(upload_to='miniaturas/%Y/%m/', storage=get_marketing_storage, blank=True)
    duracion_seg = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    costo_estimado_usd = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal('0'))
    costo_real_usd = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal('0'))
    intentos = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)
    datos_trabajo = models.JSONField(default=dict, blank=True, help_text='Estado interno del worker.')

    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    aprobada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    aprobada_en = models.DateTimeField(null=True, blank=True)
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Pieza'
        verbose_name_plural = 'Piezas'
        ordering = ['-creada']
        indexes = [models.Index(fields=['estado', 'creada'])]

    def __str__(self):
        return f'{self.get_tipo_display()} #{self.pk} - {self.campana.titulo}'

    @property
    def dimensiones(self):
        return DIMENSIONES_FORMATO.get(self.formato, (1080, 1920))

    @property
    def esta_en_proceso(self):
        return self.estado in ('pendiente', 'generando', 'ensamblando')


class Elemento(models.Model):
    """Una escena (video) o diapositiva (imagen/carrusel) de una pieza."""
    TIPO_CHOICES = [('escena', 'Escena de video'), ('diapositiva', 'Diapositiva / imagen')]
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('generando', 'Generando'),
        ('listo', 'Listo'),
        ('fallido', 'Fallido'),
    ]

    pieza = models.ForeignKey(Pieza, on_delete=models.CASCADE, related_name='elementos')
    orden = models.PositiveSmallIntegerField(default=1)
    tipo = models.CharField(max_length=12, choices=TIPO_CHOICES, default='escena')
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='pendiente')

    texto_pantalla = models.CharField(max_length=300, blank=True)
    locucion = models.TextField(blank=True)
    prompt_visual = models.TextField(blank=True)
    duracion_seg = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('4'))
    activo_referencia = models.ForeignKey(
        Activo, on_delete=models.SET_NULL, null=True, blank=True, related_name='elementos',
    )

    archivo = models.FileField(upload_to='elementos/%Y/%m/', storage=get_marketing_storage, blank=True)
    proveedor = models.CharField(max_length=50, blank=True)
    trabajo_externo_id = models.CharField(max_length=200, blank=True)
    costo_usd = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal('0'))
    error = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Elemento'
        verbose_name_plural = 'Elementos'
        ordering = ['pieza', 'orden']
        constraints = [
            models.UniqueConstraint(fields=['pieza', 'orden'], name='elemento_orden_unico'),
        ]

    def __str__(self):
        return f'{self.get_tipo_display()} {self.orden} de pieza #{self.pieza_id}'


# ══════════════════════════════════════════════════════════════════════════
# PUBLICACIÓN (manual por ahora)
# ══════════════════════════════════════════════════════════════════════════

class Publicacion(models.Model):
    ESTADO_CHOICES = [
        ('preparada', 'Preparada (lista para publicar a mano)'),
        ('publicada', 'Publicada'),
        ('descartada', 'Descartada'),
    ]

    pieza = models.ForeignKey(Pieza, on_delete=models.CASCADE, related_name='publicaciones')
    red = models.CharField(max_length=10, choices=REDES_CHOICES)
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='preparada')
    caption = models.TextField(blank=True)
    hashtags = models.CharField(max_length=500, blank=True)
    programada_para = models.DateTimeField(
        null=True, blank=True, help_text='Recordatorio interno; la publicación es manual.',
    )

    url_publica = models.URLField(blank=True)
    publicada_en = models.DateTimeField(null=True, blank=True)
    etiqueta_ia_activada = models.BooleanField(
        default=False,
        help_text='Confirmo que activé la etiqueta de contenido generado con IA en la red (si aplica).',
    )
    registrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Publicación'
        verbose_name_plural = 'Publicaciones'
        ordering = ['-creada']

    def __str__(self):
        return f'{self.get_red_display()} - pieza #{self.pieza_id} ({self.get_estado_display()})'

    def marcar_publicada(self, usuario, url=''):
        self.estado = 'publicada'
        self.url_publica = url
        self.publicada_en = timezone.now()
        self.registrada_por = usuario
        self.save(update_fields=['estado', 'url_publica', 'publicada_en', 'registrada_por'])


# ══════════════════════════════════════════════════════════════════════════
# GASTO Y AUDITORÍA
# ══════════════════════════════════════════════════════════════════════════

class RegistroGasto(models.Model):
    CAPACIDAD_CHOICES = [
        ('texto', 'Texto'), ('imagen', 'Imagen'), ('video', 'Video'), ('voz', 'Voz'), ('otro', 'Otro'),
    ]

    pieza = models.ForeignKey(Pieza, on_delete=models.SET_NULL, null=True, blank=True, related_name='gastos')
    elemento = models.ForeignKey(Elemento, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    proveedor = models.CharField(max_length=50)
    capacidad = models.CharField(max_length=10, choices=CAPACIDAD_CHOICES, default='otro')
    concepto = models.CharField(max_length=200, blank=True)
    monto_usd = models.DecimalField(max_digits=8, decimal_places=4)
    es_estimado = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Registro de gasto'
        verbose_name_plural = 'Registro de gastos'
        ordering = ['-creado']
        indexes = [models.Index(fields=['creado'])]

    def __str__(self):
        return f'{self.proveedor} ${self.monto_usd} ({self.creado:%Y-%m-%d})'

    @classmethod
    def total_mes(cls, fecha=None):
        """Gasto total (USD) del mes calendario de `fecha` (por defecto, el actual)."""
        fecha = fecha or timezone.localdate()
        total = cls.objects.filter(
            creado__year=fecha.year, creado__month=fecha.month,
        ).aggregate(t=Sum('monto_usd'))['t']
        return total or Decimal('0')


class AuditoriaMarketing(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    accion = models.CharField(max_length=60)
    objeto_tipo = models.CharField(max_length=60, blank=True)
    objeto_id = models.CharField(max_length=40, blank=True)
    detalle = models.JSONField(default=dict, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Auditoría'
        verbose_name_plural = 'Auditoría'
        ordering = ['-creado']

    def __str__(self):
        return f'{self.accion} ({self.creado:%Y-%m-%d %H:%M})'
