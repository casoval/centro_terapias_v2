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
