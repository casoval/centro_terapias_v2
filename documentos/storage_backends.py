"""
Storage de Cloudflare R2 para los documentos de pacientes.

R2 es compatible con la API de S3, así que se usa django-storages
(backend S3Boto3Storage) apuntando al endpoint de R2. Completamente
independiente del storage de Cloudinary que sigue usando `Paciente.foto`.

ACCESO PRIVADO CON URLS FIRMADAS (recomendado para datos clínicos):
El bucket de R2 se mantiene privado (sin "Public Access"). Cada vez que se
pide la URL de un documento (`documento.archivo.url`), se genera un enlace
firmado que expira solo después de `R2_URL_EXPIRACION_SEGUNDOS` (por
defecto 1 hora). Pasado ese tiempo, el link deja de funcionar aunque
alguien lo haya guardado o compartido — no queda expuesto para siempre
como pasaría con un bucket público.

Si R2 no está configurado (ej: desarrollo local sin variables de entorno),
`get_documentos_storage()` retorna None y el FileField cae automáticamente
al storage por defecto de Django (MEDIA_ROOT local), sin romper nada.
"""

from django.conf import settings

R2_URL_EXPIRACION_SEGUNDOS = 3600  # 1 hora


def get_documentos_storage():
    if not getattr(settings, 'R2_CONFIGURADO', False):
        return None

    from storages.backends.s3boto3 import S3Boto3Storage

    class R2DocumentosStorage(S3Boto3Storage):
        bucket_name = settings.CLOUDFLARE_R2_BUCKET_NAME
        endpoint_url = settings.CLOUDFLARE_R2_ENDPOINT_URL
        access_key = settings.CLOUDFLARE_R2_ACCESS_KEY_ID
        secret_key = settings.CLOUDFLARE_R2_SECRET_ACCESS_KEY
        region_name = 'auto'
        addressing_style = 'path'
        file_overwrite = False           # nunca sobrescribir un archivo con el mismo nombre
        default_acl = None                # bucket privado, sin ACLs públicas
        querystring_auth = True           # genera URLs firmadas (expiran solas)
        querystring_expire = R2_URL_EXPIRACION_SEGUNDOS
        custom_domain = None               # sin dominio público: no aplica en modo privado

    return R2DocumentosStorage()
