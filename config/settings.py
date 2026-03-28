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
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
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
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

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
    SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
    SESSION_CACHE_ALIAS = 'default'
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

if IS_PRODUCTION:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
else:
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

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
    cloudinary.config(
        cloud_name='dwwfzxo3z',
        api_key='447784864842837',
        api_secret='WH8t6i2L3ZJLic5mFNVEmq6PNig',
        secure=True
    )
    CLOUDINARY_STORAGE = {
        'CLOUD_NAME': 'dwwfzxo3z',
        'API_KEY': '447784864842837',
        'API_SECRET': 'WH8t6i2L3ZJLic5mFNVEmq6PNig',
    }

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