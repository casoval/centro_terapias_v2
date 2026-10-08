"""
Django settings for config project.
✅ Listo para producción en Hostinger VPS
"""

from pathlib import Path
import os
import dj_database_url
from dotenv import load_dotenv

load_dotenv()

# --------------------------------------------------
# BASE
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

# --------------------------------------------------
# ENTORNO
# --------------------------------------------------

ENVIRONMENT = os.environ.get('ENVIRONMENT', 'development')
IS_PRODUCTION = ENVIRONMENT == 'production'

# --------------------------------------------------
# SECURITY
# --------------------------------------------------

# ⚠️ SEGURIDAD: antes, si faltaba la variable de entorno SECRET_KEY, Django
# arrancaba igual usando un valor por defecto fijo y visible en este mismo
# archivo (público en GitHub). SECRET_KEY firma sesiones, tokens CSRF y
# tokens de recuperación de contraseña — si alguien lo conoce, puede
# falsificar sesiones o tokens. En producción ahora se exige explícitamente
# y el arranque falla si no está configurado, en vez de arrancar inseguro
# en silencio. En desarrollo se mantiene un valor por defecto (no crítico,
# nadie expone su entorno local a internet).
if IS_PRODUCTION:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise ValueError(
            "❌ Falta la variable de entorno SECRET_KEY en producción. "
            "Nunca debe arrancar con un valor por defecto en este entorno."
        )
else:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dev-key-CHANGE-IN-PRODUCTION')

DEBUG = not IS_PRODUCTION

if IS_PRODUCTION:
    allowed = os.environ.get('ALLOWED_HOSTS', '')
    ALLOWED_HOSTS = [h.strip() for h in allowed.split(',') if h.strip()] + ['127.0.0.1', 'localhost']
else:
    ALLOWED_HOSTS = ['*']

# --------------------------------------------------
# APPLICATION DEFINITION
# --------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',

    # Cloudinary DESPUÉS de staticfiles
    'cloudinary_storage',
    'cloudinary',

    # Apps del proyecto
    'core',
    'pacientes',
    'servicios',
    'agenda',
    'profesionales',
    'facturacion.apps.FacturacionConfig',
    'egresos.apps.EgresosConfig',
    'chat',
    'evaluaciones.apps.EvaluacionesConfig',
    'asistencia.apps.AsistenciaConfig',
    'rest_framework',    # ← nueva
    'recordatorios',     # ← nueva
    'agente',
    'documentos',        # ← nueva: documentos/informes de pacientes
    'archivos_centro',   # ← nueva: archivos operativos del centro (no de pacientes)
    'inventario',        # ← nueva: inventario del centro (sucursales, servicios, usuarios)
    'integracion_misael_kids',  # ← nueva: API para vincular pacientes con Misael Kids
    'marketing',        # ← nueva: publicidad con IA (solo superusuario, independiente de pacientes)
]

MIDDLEWARE = [
    # GZip va primero en la lista para comprimir la respuesta al final
    # (el procesamiento de la respuesta se hace en orden inverso), después
    # de que el resto de middlewares ya hayan terminado de armarla.
    'django.middleware.gzip.GZipMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # ✅ Corta el acceso de pacientes/profesionales/recepcionistas/gerentes
    # inactivos aunque ya tengan sesión de navegador iniciada. No modifica
    # sesiones de terapia, pagos, ni ninguna otra lógica del sistema.
    'core.middleware.AccesoActivoMiddleware',
]

# --------------------------------------------------
# AUTENTICACIÓN
# --------------------------------------------------
# ✅ Backend propio (hereda de ModelBackend) que además de usuario/contraseña
# verifica que el usuario no esté inactivo (paciente, profesional,
# recepcionista o gerente). No cambia el mecanismo de login/contraseña.
AUTHENTICATION_BACKENDS = [
    'core.backends.PerfilActivoModelBackend',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.perf_flags',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ⚡ RENDIMIENTO: si es True se usa static/css/tailwind.css (precompilado) en
# lugar del script cdn.tailwindcss.com, que compila CSS en el navegador en cada
# carga y en cada cambio del DOM. Se activa con USE_COMPILED_TAILWIND=1 en el .env.
USE_COMPILED_TAILWIND = os.environ.get('USE_COMPILED_TAILWIND', '0') == '1'

# --------------------------------------------------
# DATABASE
# --------------------------------------------------

if IS_PRODUCTION:
    DATABASES = {
        'default': dj_database_url.parse(
            os.environ.get('DATABASE_URL'),
            conn_max_age=600,
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
            'OPTIONS': {
                'timeout': 20,
            }
        }
    }

if not IS_PRODUCTION:
    DATABASES['default']['CONN_MAX_AGE'] = 60

# --------------------------------------------------
# CACHE
# --------------------------------------------------

if IS_PRODUCTION:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'centro-cache',
            'TIMEOUT': 300,
            'OPTIONS': {'MAX_ENTRIES': 1000}
        }
    }
    SESSION_ENGINE = 'django.contrib.sessions.backends.db'
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        }
    }

# --------------------------------------------------
# PASSWORD VALIDATION
# --------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 4}
    },
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --------------------------------------------------
# INTERNATIONALIZATION
# --------------------------------------------------

LANGUAGE_CODE = 'es-bo'
TIME_ZONE = 'America/La_Paz'
USE_I18N = True
USE_L10N = True
USE_TZ = True

LOCALE_PATHS = [BASE_DIR / 'locale']

DATE_FORMAT = 'd/m/Y'
DATETIME_FORMAT = 'd/m/Y H:i'
SHORT_DATE_FORMAT = 'd/m/Y'

# --------------------------------------------------
# STATIC FILES
# --------------------------------------------------

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles_collected'
STATICFILES_DIRS = [BASE_DIR / 'static']

STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
]

# ⚡ RENDIMIENTO: Django 5.1+ (esta app usa Django 6) IGNORA los ajustes
# STATICFILES_STORAGE y DEFAULT_FILE_STORAGE; hay que usar STORAGES. Antes,
# WhiteNoise no estaba comprimiendo los estáticos en producción.
# Se usa CompressedStaticFilesStorage (gzip/brotli al hacer collectstatic) y
# NO la variante "Manifest" a propósito: esta exigiría correr collectstatic en
# cada deploy y rompería con error 500 si falta el manifiesto.
# El almacenamiento por defecto de archivos se deja explícito igual que hoy
# (las fotos usan CloudinaryField y no dependen de este ajuste).
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': (
            'whitenoise.storage.CompressedStaticFilesStorage'
            if IS_PRODUCTION
            else 'django.contrib.staticfiles.storage.StaticFilesStorage'
        ),
    },
}

# ⚡ RENDIMIENTO: sin nombres con hash, WhiteNoise cacheaba los estáticos solo
# 60 segundos (logos e imágenes se volvían a descargar a cada rato).
# 1 día = buen equilibrio; si cambias una imagen con el mismo nombre, los
# usuarios la verán actualizada como máximo en 24 h.
WHITENOISE_MAX_AGE = 60 * 60 * 24 if IS_PRODUCTION else 0

# --------------------------------------------------
# MEDIA FILES
# --------------------------------------------------

MEDIA_URL = '/media/'

if IS_PRODUCTION:
    DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'
else:
    MEDIA_ROOT = BASE_DIR / 'media'

# --------------------------------------------------
# AUTH REDIRECTS
# --------------------------------------------------

LOGIN_URL = 'core:login'
LOGIN_REDIRECT_URL = 'core:dashboard'
LOGOUT_REDIRECT_URL = 'core:login'

# --------------------------------------------------
# DEFAULT PK
# --------------------------------------------------

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --------------------------------------------------
# LOGGING
# --------------------------------------------------

LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'django.log',
            'maxBytes': 1024 * 1024 * 5,
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'facturacion': {
            'handlers': ['console', 'file'] if IS_PRODUCTION else ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'egresos': {
            'handlers': ['console', 'file'] if IS_PRODUCTION else ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'asistencia': {
            'handlers': ['console', 'file'] if IS_PRODUCTION else ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'agente': {
            'handlers': ['console', 'file'] if IS_PRODUCTION else ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# --------------------------------------------------
# LIMITES DE CARGA
# --------------------------------------------------

DATA_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5 MB

# --------------------------------------------------
# ASISTENCIA
# --------------------------------------------------

EMAIL_RRHH = os.environ.get('EMAIL_RRHH', 'rrhh@tucentro.com')

# ── Integración con Misael Kids ────────────────────────────────────
# Clave compartida que Misael Kids debe enviar en el header
# "Authorization: ApiKey <clave>" para consumir la API de
# integracion_misael_kids. Debe ser la misma en ambos lados (ver
# CENTRO_MISAEL_API_KEY en el .env de misael_kids).
MISAEL_KIDS_API_KEY = os.environ.get('MISAEL_KIDS_API_KEY', '')

# URL base de Misael Kids, para las llamadas SALIENTES desde Centro
# Misael (ej. preguntar si un paciente ya está vinculado). Usa la misma
# MISAEL_KIDS_API_KEY como secreto compartido en ambos sentidos.
MISAEL_KIDS_API_URL = os.environ.get('MISAEL_KIDS_API_URL', '')

# --------------------------------------------------
# SEGURIDAD EN PRODUCCIÓN
# --------------------------------------------------

if IS_PRODUCTION:
    # ⚠️ SECURE_SSL_REDIRECT se activa SOLO después de instalar SSL con certbot
    # Descomenta esta línea cuando tengas HTTPS funcionando:
    # SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

else:
    print("\n" + "="*60)
    print("🔧 MODO DESARROLLO ACTIVADO")
    print("="*60)
    print(f"   DEBUG = {DEBUG}")
    print(f"   Base de datos: SQLite local")
    print(f"   Cache: DESACTIVADO (DummyCache)")
    print("="*60 + "\n")

# --------------------------------------------------
# CLOUDINARY
# --------------------------------------------------

import cloudinary
import cloudinary.uploader
import cloudinary.api

if IS_PRODUCTION:
    _cloud_name   = os.environ.get('CLOUDINARY_CLOUD_NAME')
    _api_key      = os.environ.get('CLOUDINARY_API_KEY')
    _api_secret   = os.environ.get('CLOUDINARY_API_SECRET')

    if not all([_cloud_name, _api_key, _api_secret]):
        raise ValueError(
            "❌ Faltan variables de Cloudinary en el .env de producción. "
            "Verifica CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY y CLOUDINARY_API_SECRET."
        )

    cloudinary.config(cloud_name=_cloud_name, api_key=_api_key, api_secret=_api_secret, secure=True)
    CLOUDINARY_STORAGE = {'CLOUD_NAME': _cloud_name, 'API_KEY': _api_key, 'API_SECRET': _api_secret}

else:
    # ⚠️ SEGURIDAD: antes había credenciales reales de Cloudinary escritas
    # directamente aquí (hardcodeadas). Como este archivo está en un
    # repositorio público, esa API key/secret quedó expuesta a cualquiera.
    # Se corrigió para leer también desde variables de entorno en
    # desarrollo (igual que en producción). Si no están configuradas, no
    # se hardcodea ningún valor real: Cloudinary queda sin credenciales
    # válidas y las subidas de imágenes fallarán de forma visible en vez
    # de usar una cuenta ajena o comprometida.
    #
    # ⚠️ IMPORTANTE: la API key/secret que estaban aquí antes deben
    # considerarse comprometidas (estuvieron públicas en GitHub) y hay que
    # rotarlas/regenerarlas desde el dashboard de Cloudinary cuanto antes,
    # sin importar si se aplica este fix o no.
    _cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME', '')
    _api_key    = os.environ.get('CLOUDINARY_API_KEY', '')
    _api_secret = os.environ.get('CLOUDINARY_API_SECRET', '')

    if not all([_cloud_name, _api_key, _api_secret]):
        print(
            "⚠️  Cloudinary no está configurado (faltan CLOUDINARY_CLOUD_NAME / "
            "CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET en tu .env local). "
            "Las subidas de imágenes no funcionarán hasta que los configures. "
            "Ver .env.example."
        )

    cloudinary.config(cloud_name=_cloud_name, api_key=_api_key, api_secret=_api_secret, secure=True)
    CLOUDINARY_STORAGE = {
        'CLOUD_NAME': _cloud_name,
        'API_KEY': _api_key,
        'API_SECRET': _api_secret,
    }

# --------------------------------------------------
# CLOUDFLARE R2 (almacenamiento de documentos de pacientes)
# --------------------------------------------------
# Independiente de Cloudinary: las fotos de pacientes siguen en Cloudinary,
# solo los documentos/informes (documentos.DocumentoPaciente) usan R2.
# El bucket se mantiene PRIVADO (sin Public Access) — se accede vía URLs
# firmadas que expiran solas (ver documentos/storage_backends.py).
# Requiere las siguientes variables de entorno en producción:
#   CLOUDFLARE_R2_ACCESS_KEY_ID
#   CLOUDFLARE_R2_SECRET_ACCESS_KEY
#   CLOUDFLARE_R2_BUCKET_NAME
#   CLOUDFLARE_R2_ENDPOINT_URL       (ej: https://<account_id>.r2.cloudflarestorage.com)

if IS_PRODUCTION:
    CLOUDFLARE_R2_ACCESS_KEY_ID = os.environ.get('CLOUDFLARE_R2_ACCESS_KEY_ID')
    CLOUDFLARE_R2_SECRET_ACCESS_KEY = os.environ.get('CLOUDFLARE_R2_SECRET_ACCESS_KEY')
    CLOUDFLARE_R2_BUCKET_NAME = os.environ.get('CLOUDFLARE_R2_BUCKET_NAME')
    CLOUDFLARE_R2_ENDPOINT_URL = os.environ.get('CLOUDFLARE_R2_ENDPOINT_URL')

    if not all([
        CLOUDFLARE_R2_ACCESS_KEY_ID, CLOUDFLARE_R2_SECRET_ACCESS_KEY,
        CLOUDFLARE_R2_BUCKET_NAME, CLOUDFLARE_R2_ENDPOINT_URL,
    ]):
        raise ValueError(
            "❌ Faltan variables de Cloudflare R2 en el .env de producción. "
            "Verifica CLOUDFLARE_R2_ACCESS_KEY_ID, CLOUDFLARE_R2_SECRET_ACCESS_KEY, "
            "CLOUDFLARE_R2_BUCKET_NAME y CLOUDFLARE_R2_ENDPOINT_URL."
        )
else:
    # En desarrollo, si no configuraste R2 localmente, los documentos caen a
    # almacenamiento local (MEDIA_ROOT) automáticamente — no rompe el entorno de dev.
    CLOUDFLARE_R2_ACCESS_KEY_ID = os.environ.get('CLOUDFLARE_R2_ACCESS_KEY_ID', '')
    CLOUDFLARE_R2_SECRET_ACCESS_KEY = os.environ.get('CLOUDFLARE_R2_SECRET_ACCESS_KEY', '')
    CLOUDFLARE_R2_BUCKET_NAME = os.environ.get('CLOUDFLARE_R2_BUCKET_NAME', '')
    CLOUDFLARE_R2_ENDPOINT_URL = os.environ.get('CLOUDFLARE_R2_ENDPOINT_URL', '')

R2_CONFIGURADO = all([
    CLOUDFLARE_R2_ACCESS_KEY_ID, CLOUDFLARE_R2_SECRET_ACCESS_KEY,
    CLOUDFLARE_R2_BUCKET_NAME, CLOUDFLARE_R2_ENDPOINT_URL,
])

# ☁️ ALMACENAMIENTO POR DEFECTO EN SERVIDOR EXTERNO (R2)
# Django 5.1+ ignora DEFAULT_FILE_STORAGE, por lo que los FileField/ImageField
# SIN storage propio (egresos.comprobante, ingresos adicionales.comprobante,
# asistencia.foto_captura) se estaban guardando en el disco local del servidor,
# donde no se sirven (/media/ solo se enruta con DEBUG=True) y pueden perderse
# en un redeploy. En producción ahora usan el mismo bucket privado de R2 que
# `documentos` (URLs firmadas que expiran). Las fotos de pacientes/profesionales
# no cambian: usan CloudinaryField. En desarrollo sigue el disco local.
if IS_PRODUCTION and R2_CONFIGURADO:
    STORAGES['default'] = {'BACKEND': 'documentos.storage_backends.R2DocumentosStorage'}

# --------------------------------------------------
# CLOUDFLARE R2 - MARKETING (bucket SEPARADO del de pacientes)
# --------------------------------------------------
# Módulo `marketing`: publicidad con IA. Usa su propio bucket privado y su
# propio token (idealmente limitado a ese bucket). Variables en el .env:
#   MARKETING_R2_ACCESS_KEY_ID
#   MARKETING_R2_SECRET_ACCESS_KEY
#   MARKETING_R2_BUCKET_NAME
#   MARKETING_R2_ENDPOINT_URL
# A diferencia de R2 de documentos, aquí NO se aborta el arranque si faltan en
# producción: solo falla el guardado de archivos de marketing (con un mensaje
# claro) y el resto del sistema sigue funcionando. Ver marketing/storage_backends.py
MARKETING_R2_ACCESS_KEY_ID = os.environ.get('MARKETING_R2_ACCESS_KEY_ID', '')
MARKETING_R2_SECRET_ACCESS_KEY = os.environ.get('MARKETING_R2_SECRET_ACCESS_KEY', '')
MARKETING_R2_BUCKET_NAME = os.environ.get('MARKETING_R2_BUCKET_NAME', '')
MARKETING_R2_ENDPOINT_URL = os.environ.get('MARKETING_R2_ENDPOINT_URL', '')
MARKETING_R2_CONFIGURADO = all([
    MARKETING_R2_ACCESS_KEY_ID, MARKETING_R2_SECRET_ACCESS_KEY,
    MARKETING_R2_BUCKET_NAME, MARKETING_R2_ENDPOINT_URL,
])

# --------------------------------------------------
# DEBUG TOOLBAR (solo desarrollo)
# --------------------------------------------------

if DEBUG and not IS_PRODUCTION:
    try:
        import debug_toolbar
        INSTALLED_APPS += ['debug_toolbar']
        MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')
        INTERNAL_IPS = ['127.0.0.1', 'localhost']
        DEBUG_TOOLBAR_CONFIG = {'SHOW_TOOLBAR_CALLBACK': lambda request: DEBUG}
        print("✅ Django Debug Toolbar habilitado")
    except ImportError:
        pass