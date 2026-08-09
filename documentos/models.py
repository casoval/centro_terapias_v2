from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from .storage_backends import get_documentos_storage

_DOCUMENTOS_STORAGE = get_documentos_storage()


EXTENSIONES_PERMITIDAS = [
    'pdf', 'doc', 'docx', 'odt',
    'jpg', 'jpeg', 'png', 'webp',
    'xls', 'xlsx',
]

# 20 MB — protege el plan de almacenamiento (Cloudinary), no la cantidad de archivos
TAMANO_MAXIMO_MB = 20


def validar_tamano_archivo(archivo):
    limite = TAMANO_MAXIMO_MB * 1024 * 1024
    if archivo.size > limite:
        raise ValidationError(f'El archivo supera el tamaño máximo permitido ({TAMANO_MAXIMO_MB} MB).')


class DocumentoPaciente(models.Model):
    """
    Documento/archivo asociado a un paciente.

    Puede estar ligado a UN Proyecto, a UNA Mensualidad, o a ninguno
    de los dos (documento general del paciente). Nunca a ambos a la vez.

    Reglas de permisos (ver PerfilUsuario en core.models):
      - Suben: profesional (solo "sus" pacientes), gerente y admin (todos), sin límite de cantidad.
      - Ven: los anteriores + recepcionista (solo lectura).
      - Borran: solo admin (superusuario).
    """

    TIPO_CHOICES = [
        ('proyecto', 'Informe de Proyecto/Evaluación'),
        ('mensualidad', 'Informe de Mensualidad'),
        ('general', 'Documento General del Paciente'),
    ]

    paciente = models.ForeignKey(
        'pacientes.Paciente',
        on_delete=models.CASCADE,
        related_name='documentos',
    )
    proyecto = models.ForeignKey(
        'agenda.Proyecto',
        on_delete=models.CASCADE,
        related_name='documentos',
        null=True,
        blank=True,
    )
    mensualidad = models.ForeignKey(
        'agenda.Mensualidad',
        on_delete=models.CASCADE,
        related_name='documentos',
        null=True,
        blank=True,
    )

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='general')
    titulo = models.CharField(max_length=200, help_text='Nombre descriptivo del documento')
    descripcion = models.TextField(blank=True)

    archivo = models.FileField(
        upload_to='documentos_pacientes/%Y/%m/',
        storage=_DOCUMENTOS_STORAGE,  # Cloudflare R2, o local si no está configurado (dev)
        validators=[
            FileExtensionValidator(allowed_extensions=EXTENSIONES_PERMITIDAS),
            validar_tamano_archivo,
        ],
    )

    subido_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='documentos_subidos',
    )
    fecha_subida = models.DateTimeField(auto_now_add=True)

    # ── Integración con Misael Kids ────────────────────────────────
    # Si el profesional marca esto, el documento (plan de trabajo,
    # informe, etc.) queda visible para el jardín Misael Kids a través
    # de la API de integración, sin importar si el paciente está
    # activo o inactivo en Centro Misael.
    compartir_misael_kids = models.BooleanField(
        default=False,
        verbose_name='Compartir con Misael Kids',
        help_text='Visible para la educadora del jardín como plan de trabajo del niño.',
    )

    class Meta:
        verbose_name = 'Documento de Paciente'
        verbose_name_plural = 'Documentos de Pacientes'
        ordering = ['-fecha_subida']
        indexes = [
            models.Index(fields=['paciente', '-fecha_subida']),
            models.Index(fields=['proyecto']),
            models.Index(fields=['mensualidad']),
        ]

    def __str__(self):
        return f'{self.titulo} — {self.paciente} ({self.get_tipo_display()})'

    def clean(self):
        if self.proyecto_id and self.mensualidad_id:
            raise ValidationError(
                'Un documento no puede estar ligado a un proyecto y a una mensualidad al mismo tiempo.'
            )
        if self.proyecto_id and self.proyecto.paciente_id != self.paciente_id:
            raise ValidationError('El proyecto seleccionado no pertenece a este paciente.')
        if self.mensualidad_id and self.mensualidad.paciente_id != self.paciente_id:
            raise ValidationError('La mensualidad seleccionada no pertenece a este paciente.')

        # Auto-clasificar el tipo según lo que se haya ligado
        if self.proyecto_id:
            self.tipo = 'proyecto'
        elif self.mensualidad_id:
            self.tipo = 'mensualidad'
        else:
            self.tipo = 'general'

    @property
    def nombre_archivo(self):
        return self.archivo.name.rsplit('/', 1)[-1]

    @property
    def extension(self):
        return self.nombre_archivo.rsplit('.', 1)[-1].lower() if '.' in self.nombre_archivo else ''

    @property
    def icono(self):
        """Emoji simple según extensión, para no depender de librerías de iconos."""
        ext = self.extension
        if ext == 'pdf':
            return '📕'
        if ext in ('doc', 'docx', 'odt'):
            return '📘'
        if ext in ('xls', 'xlsx'):
            return '📗'
        if ext in ('jpg', 'jpeg', 'png', 'webp'):
            return '🖼️'
        return '📎'


class PlanTrabajo(models.Model):
    """
    Plan de trabajo que un profesional del Centro Misael crea para un
    paciente vinculado con Misael Kids, con su propio documento adjunto.

    Reemplaza el uso de DocumentoPaciente.compartir_misael_kids para
    este caso: antes se mezclaba con el formulario genérico de
    proyecto/mensualidad/general, lo que era confuso. Ahora es un
    formulario propio, sin selector de niño (el paciente ya viene fijo),
    sin "derivación relacionada" y sin email — solo los datos que el
    profesional realmente necesita completar a mano.

    Puede haber VARIOS planes por paciente (uno por profesional/área).
    Misael Kids los consulta en vivo, de solo lectura, vía la API de
    integración — nunca los crea ni los edita.
    """

    paciente = models.ForeignKey(
        'pacientes.Paciente',
        on_delete=models.CASCADE,
        related_name='planes_trabajo',
    )

    profesional = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='planes_trabajo_creados',
        help_text='Quién creó el registro. Si es un profesional, su nombre se usa tal cual.',
    )
    nombre_profesional_manual = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='Nombre del profesional (si lo carga otro rol)',
        help_text='Solo completar si quien sube el plan NO es el propio profesional '
                   '(ej. gerente o admin cargándolo en nombre de un profesional externo).',
    )

    telefono = models.CharField(max_length=20, blank=True, verbose_name='Teléfono del profesional')
    area_intervencion = models.CharField(max_length=150, verbose_name='Área de intervención')
    frecuencia_sesiones = models.CharField(
        max_length=100, blank=True,
        help_text='Ej: 2 veces por semana',
    )

    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(null=True, blank=True, help_text='Vacío = plan vigente')
    proxima_revision = models.DateField(
        null=True, blank=True,
        help_text='Cuándo toca revisar/renovar el plan',
    )

    descripcion = models.TextField(help_text='Objetivos y lineamientos del plan')
    notas_seguimiento = models.TextField(
        blank=True,
        help_text='Avances, observaciones, ajustes acordados',
    )

    archivo = models.FileField(
        upload_to='planes_trabajo/%Y/%m/',
        storage=_DOCUMENTOS_STORAGE,
        validators=[
            FileExtensionValidator(allowed_extensions=EXTENSIONES_PERMITIDAS),
            validar_tamano_archivo,
        ],
        null=True,
        blank=True,
        help_text='Informe o documento del plan, opcional',
    )

    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Plan de trabajo'
        verbose_name_plural = 'Planes de trabajo'
        ordering = ['-fecha_inicio']
        indexes = [
            models.Index(fields=['paciente', '-fecha_inicio']),
        ]

    def __str__(self):
        return f'Plan de trabajo — {self.paciente} ({self.nombre_profesional})'

    @property
    def nombre_profesional(self):
        """Nombre a mostrar: el del profesional autor, o el cargado a mano si lo subió otro rol."""
        if self.nombre_profesional_manual:
            return self.nombre_profesional_manual
        return self.profesional.get_full_name() or self.profesional.username

    @property
    def nombre_archivo(self):
        if not self.archivo:
            return ''
        return self.archivo.name.rsplit('/', 1)[-1]
