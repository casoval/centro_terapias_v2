from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from .storage_backends import get_archivos_centro_storage

_ARCHIVOS_CENTRO_STORAGE = get_archivos_centro_storage()

# Choices de rol duplicadas de core.PerfilUsuario.ROL_CHOICES a propósito:
# aquí se usan solo como choices de un CharField (no como FK), para no
# acoplar las migraciones de esta app a los cambios de rol en `core`.
ROL_CHOICES = [
    ('paciente', 'Paciente'),
    ('profesional', 'Profesional'),
    ('recepcionista', 'Recepcionista'),
    ('gerente', 'Gerente'),
]

# Subconjunto de ROL_CHOICES sin 'paciente': los pacientes no tienen acceso
# a este módulo en absoluto, así que no tiene sentido ofrecerlos como opción
# al dar permisos por rol a un archivo (a diferencia de ROL_CHOICES completo,
# que sigue existiendo tal cual porque es el choices del CharField `rol` de
# ArchivoRolPermitido, reutilizado en otras partes del proyecto).
ROLES_STAFF_CHOICES = [c for c in ROL_CHOICES if c[0] != 'paciente']

EXTENSIONES_PERMITIDAS = [
    'pdf', 'doc', 'docx', 'odt', 'txt',
    'jpg', 'jpeg', 'png', 'webp',
    'xls', 'xlsx', 'csv',
    'ppt', 'pptx',
    'zip', 'rar',
]

# 30 MB — son archivos administrativos/operativos del centro, no clínicos
TAMANO_MAXIMO_MB = 30


def validar_tamano_archivo(archivo):
    limite = TAMANO_MAXIMO_MB * 1024 * 1024
    if archivo.size > limite:
        raise ValidationError(f'El archivo supera el tamaño máximo permitido ({TAMANO_MAXIMO_MB} MB).')


class CategoriaArchivo(models.Model):
    """
    Carpeta/categoría simple para ordenar los archivos del centro.
    Solo admin y gerente pueden crear/editar/eliminar categorías
    (ver archivos_centro.permissions.puede_gestionar_categorias);
    cualquier usuario staff puede usarlas al subir un archivo.
    """
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.CharField(max_length=255, blank=True)
    creada_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='categorias_archivo_creadas',
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Categoría de Archivo'
        verbose_name_plural = 'Categorías de Archivos'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class ArchivoCentro(models.Model):
    """
    Archivo/documento operativo del centro (NO de pacientes): manuales,
    protocolos, planillas, contratos, material de recepción, etc.

    Reglas de permisos (ver archivos_centro.permissions):
      - Suben: cualquier usuario staff (profesional, recepcionista,
        gerente, admin). Los pacientes no tienen acceso a este módulo.
      - Ven: el admin ve todo siempre. El dueño ve lo suyo siempre.
        Según `visibilidad`: todos / solo roles específicos (ver
        `ArchivoRolPermitido`) / solo usuarios específicos (ver
        `ArchivoUsuarioPermitido`) / privado (solo el dueño).
      - Al subir, el usuario común solo puede elegir entre 'privado' y
        'todos' (simple). Las visibilidades 'roles' y 'usuarios' solo
        las asigna el admin, desde cualquier archivo, en cualquier momento.
      - Borran: solo admin (superusuario).
    """

    VISIBILIDAD_CHOICES = [
        ('privado', 'Solo quien lo subió'),
        ('todos', 'Todos en el centro'),
        ('roles', 'Solo ciertos roles (definido por admin)'),
        ('usuarios', 'Solo ciertos usuarios (definido por admin)'),
    ]

    # Visibilidades que un usuario común (no admin) puede elegir al subir/editar lo suyo
    VISIBILIDAD_SIMPLE_CHOICES = [
        ('privado', 'Solo yo'),
        ('todos', 'Todos en el centro'),
    ]

    titulo = models.CharField(max_length=200, help_text='Nombre descriptivo del archivo')
    descripcion = models.TextField(blank=True)
    categoria = models.ForeignKey(
        CategoriaArchivo, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='archivos',
    )

    archivo = models.FileField(
        upload_to='archivos_centro/%Y/%m/',
        storage=_ARCHIVOS_CENTRO_STORAGE,
        validators=[
            FileExtensionValidator(allowed_extensions=EXTENSIONES_PERMITIDAS),
            validar_tamano_archivo,
        ],
    )

    visibilidad = models.CharField(max_length=10, choices=VISIBILIDAD_CHOICES, default='privado')

    subido_por = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='archivos_centro_subidos',
    )
    fecha_subida = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Archivo del Centro'
        verbose_name_plural = 'Archivos del Centro'
        ordering = ['-fecha_subida']
        indexes = [
            models.Index(fields=['-fecha_subida']),
            models.Index(fields=['categoria']),
            models.Index(fields=['subido_por']),
        ]

    def __str__(self):
        return self.titulo

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
        if ext in ('doc', 'docx', 'odt', 'txt'):
            return '📘'
        if ext in ('xls', 'xlsx', 'csv'):
            return '📗'
        if ext in ('ppt', 'pptx'):
            return '📙'
        if ext in ('jpg', 'jpeg', 'png', 'webp'):
            return '🖼️'
        if ext in ('zip', 'rar'):
            return '🗜️'
        return '📎'


class ArchivoRolPermitido(models.Model):
    """Roles con acceso a un archivo cuya visibilidad = 'roles'. Solo lo gestiona el admin."""
    archivo = models.ForeignKey(ArchivoCentro, on_delete=models.CASCADE, related_name='roles_permitidos')
    rol = models.CharField(max_length=20, choices=ROL_CHOICES)

    class Meta:
        verbose_name = 'Rol permitido en archivo'
        verbose_name_plural = 'Roles permitidos en archivo'
        unique_together = ('archivo', 'rol')

    def __str__(self):
        return f'{self.archivo.titulo} → {self.get_rol_display()}'


class ArchivoUsuarioPermitido(models.Model):
    """Usuarios específicos con acceso a un archivo cuya visibilidad = 'usuarios'. Solo lo gestiona el admin."""
    archivo = models.ForeignKey(ArchivoCentro, on_delete=models.CASCADE, related_name='usuarios_permitidos')
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='archivos_centro_autorizados')

    class Meta:
        verbose_name = 'Usuario permitido en archivo'
        verbose_name_plural = 'Usuarios permitidos en archivo'
        unique_together = ('archivo', 'usuario')

    def __str__(self):
        return f'{self.archivo.titulo} → {self.usuario.get_full_name() or self.usuario.username}'
