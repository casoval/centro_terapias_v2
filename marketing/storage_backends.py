"""
Storage propio del módulo de Marketing (bucket de Cloudflare R2 SEPARADO del
de documentos de pacientes).

Por qué un bucket aparte:
  - Aislamiento: un error o un token filtrado de marketing no puede tocar
    informes clínicos, y viceversa.
  - Más adelante (publicación automática en Meta/TikTok) se podrá exponer
    solo este bucket sin abrir nunca el de pacientes.

Reglas de seguridad de este archivo:
  1. NUNCA cae al storage por defecto de Django. En producción el default es
     el bucket de documentos de pacientes (ver settings.STORAGES['default']);
     si marketing cayera ahí, sus archivos terminarían mezclados con datos
     clínicos.
  2. Si en PRODUCCIÓN faltan las variables MARKETING_R2_*, el sitio NO se cae:
     solo falla la subida/guardado de archivos de marketing con un error
     claro. El resto del sistema (facturación, agenda, etc.) no se entera.
  3. En desarrollo, sin variables, se usa una carpeta local (MEDIA_ROOT/marketing).

`get_marketing_storage` es un callable (no una instancia) a propósito: así las
migraciones guardan la referencia a la función y no credenciales ni rutas.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage
from storages.backends.s3boto3 import S3Boto3Storage

MARKETING_URL_EXPIRACION_SEGUNDOS = 3600  # 1 hora


class R2MarketingStorage(S3Boto3Storage):
    """Bucket privado de marketing en R2, con URLs firmadas que expiran."""
    bucket_name = getattr(settings, 'MARKETING_R2_BUCKET_NAME', '')
    endpoint_url = getattr(settings, 'MARKETING_R2_ENDPOINT_URL', '')
    access_key = getattr(settings, 'MARKETING_R2_ACCESS_KEY_ID', '')
    secret_key = getattr(settings, 'MARKETING_R2_SECRET_ACCESS_KEY', '')
    region_name = 'auto'
    addressing_style = 'path'
    file_overwrite = False
    default_acl = None
    querystring_auth = True
    querystring_expire = MARKETING_URL_EXPIRACION_SEGUNDOS
    custom_domain = None


class MarketingNoConfiguradoStorage(FileSystemStorage):
    """
    Se usa solo en PRODUCCIÓN cuando faltan las variables MARKETING_R2_*.
    Permite que el sitio arranque normal, pero impide guardar archivos de
    marketing (en vez de enviarlos a un lugar equivocado).
    """

    def _save(self, name, content):
        raise ImproperlyConfigured(
            'El almacenamiento de Marketing no está configurado. Define '
            'MARKETING_R2_ACCESS_KEY_ID, MARKETING_R2_SECRET_ACCESS_KEY, '
            'MARKETING_R2_BUCKET_NAME y MARKETING_R2_ENDPOINT_URL en el .env '
            'del servidor.'
        )


def get_marketing_storage():
    if getattr(settings, 'MARKETING_R2_CONFIGURADO', False):
        return R2MarketingStorage()
    if getattr(settings, 'IS_PRODUCTION', False):
        return MarketingNoConfiguradoStorage(location=str(settings.BASE_DIR / 'media_marketing_no_usar'))
    return FileSystemStorage(
        location=str(settings.BASE_DIR / 'media' / 'marketing'),
        base_url=settings.MEDIA_URL + 'marketing/',
    )
