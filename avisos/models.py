from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

from documentos.storage_backends import get_documentos_storage

_STORAGE = get_documentos_storage()  # R2 si está configurado; si no, storage local

EXT_IMAGEN = ('jpg', 'jpeg', 'png', 'webp')
EXT_PERMITIDAS = EXT_IMAGEN + ('pdf',)
TAMANO_MAX_MB = 10


def validar_tamano_adjunto(f):
    from django.core.exceptions import ValidationError
    if f.size > TAMANO_MAX_MB * 1024 * 1024:
        raise ValidationError(f'El archivo no debe superar {TAMANO_MAX_MB} MB.')


class Anuncio(models.Model):
    """Anuncio publicado por el administrador (texto y/o una imagen o PDF)."""

    IMPORTANCIA_CHOICES = [('normal', 'Normal'), ('urgente', 'Urgente')]

    titulo = models.CharField('Título', max_length=150)
    mensaje = models.TextField('Mensaje', blank=True)
    adjunto = models.FileField(
        'Imagen o PDF', upload_to='avisos/%Y/%m/', storage=_STORAGE, blank=True,
        validators=[FileExtensionValidator(allowed_extensions=EXT_PERMITIDAS), validar_tamano_adjunto],
    )
    importancia = models.CharField(max_length=10, choices=IMPORTANCIA_CHOICES, default='normal')

    dest_gerentes = models.BooleanField('Gerentes', default=False)
    dest_recepcionistas = models.BooleanField('Recepcionistas', default=False)
    dest_profesionales = models.BooleanField('Profesionales', default=False)
    dest_pacientes = models.BooleanField('Pacientes', default=False)
    sucursales = models.ManyToManyField(
        'servicios.Sucursal', blank=True, related_name='anuncios',
        help_text='Vacío = todas las sucursales.',
    )

    fecha_inicio = models.DateField('Mostrar desde')
    fecha_fin = models.DateField('Mostrar hasta (inclusive)')
    guardar_en_historial = models.BooleanField(
        'Guardar en el historial', default=True,
        help_text='Si se desmarca, al terminar la vigencia se elimina por completo.',
    )
    pedir_confirmacion = models.BooleanField(
        'Pedir confirmación de lectura', default=False,
        help_text='Muestra un botón «Entendido» y registra quién lo pulsó.',
    )

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='anuncios_creados',
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_inicio', '-id']
        verbose_name = 'Anuncio'
        verbose_name_plural = 'Anuncios'

    def __str__(self):
        return self.titulo

    # -- estado de vigencia ------------------------------------------------
    def esta_vigente(self, hoy=None):
        hoy = hoy or timezone.localdate()
        return self.fecha_inicio <= hoy <= self.fecha_fin

    def es_urgente(self):
        return self.importancia == 'urgente'

    # -- adjunto -----------------------------------------------------------
    def adjunto_tipo(self):
        if not self.adjunto:
            return ''
        ext = self.adjunto.name.rsplit('.', 1)[-1].lower()
        if ext in EXT_IMAGEN:
            return 'imagen'
        return 'pdf' if ext == 'pdf' else ''

    def destinatarios_texto(self):
        partes = [n for f, n in (
            (self.dest_gerentes, 'Gerentes'), (self.dest_recepcionistas, 'Recepcionistas'),
            (self.dest_profesionales, 'Profesionales'), (self.dest_pacientes, 'Pacientes'),
        ) if f]
        if len(partes) == 4:
            return 'Todos'
        return ', '.join(partes) or 'Nadie'

    def borrar_archivo(self):
        if self.adjunto:
            try:
                self.adjunto.delete(save=False)
            except Exception:
                pass

    def delete(self, *args, **kwargs):
        self.borrar_archivo()
        return super().delete(*args, **kwargs)


class AnuncioLectura(models.Model):
    """Confirmación «Entendido» de un usuario."""

    anuncio = models.ForeignKey(Anuncio, on_delete=models.CASCADE, related_name='lecturas')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='anuncios_leidos')
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('anuncio', 'user')
        ordering = ['-fecha']
