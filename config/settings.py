"""
Django settings for config project.
✅ OPTIMIZADO: Incluye cache, conexión persistente y mejoras de performance
"""

from pathlib import Path
import os
import dj_database_url

# --------------------------------------------------
# BASE
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

# --------------------------------------------------
# ENTORNO (Detectar si es desarrollo o producción)
# --------------------------------------------------

ENVIRONMENT = os.environ.get('ENVIRONMENT', 'development')
IS_PRODUCTION = ENVIRONMENT == 'production'

# --------------------------------------------------
# SECURITY
# --------------------------------------------------

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dev-key-CHANGE-IN-PRODUCTION')

DEBUG = not IS_PRODUCTION

if IS_PRODUCTION:
    allowed = os.environ.get('ALLOWED_HOSTS', '').split(',')
    ALLOWED_HOSTS = allowed + ['127.0.0.1', 'localhost']
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
            conn_max_age=600,  # ✅ Conexión persistente (10 min)
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
            # ✅ SQLite optimizations
            'OPTIONS': {
                'timeout': 20,
                'init_command': 'PRAGMA journal_mode=WAL;',
            }
        }
    }

# ✅ OPTIMIZACIÓN: Conexiones persistentes en desarrollo también
if not IS_PRODUCTION:
    DATABASES['default']['CONN_MAX_AGE'] = 60  # 1 minuto en dev

# --------------------------------------------------
# CACHE CONFIGURATION (✅ OPTIMIZADO - Local Memory Cache)
# --------------------------------------------------

# ✅ Usar Local Memory Cache en todos los entornos
# Funciona perfecto para apps con un solo worker
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'facturacion-cache',
        'TIMEOUT': 300,  # 5 minutos
        'OPTIONS': {
            'MAX_ENTRIES': 1000,
        }
    }
}

# ✅ Cache para sesiones (mejora performance)
if IS_PRODUCTION:
    SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
    SESSION_CACHE_ALIAS = 'default'

# --------------------------------------------------
# PASSWORD VALIDATION
# --------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 4,
        }
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
STATIC_ROOT = BASE_DIR / 'staticfiles'

STATICFILES_DIRS = []

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
# PERFORMANCE OPTIMIZATIONS (✅ NUEVO)
# --------------------------------------------------

# ✅ Logging configurado para performance
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
            'filename': BASE_DIR / 'logs' / 'django.log',
            'maxBytes': 1024 * 1024 * 5,  # 5 MB
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
    },
}

# ✅ Crear directorio de logs si no existe
(BASE_DIR / 'logs').mkdir(exist_ok=True)

# ✅ Data upload limits
DATA_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5 MB

# --------------------------------------------------
# CONFIGURACIONES ADICIONALES SEGÚN ENTORNO
# --------------------------------------------------

if IS_PRODUCTION:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    
    # ✅ HSTS (HTTP Strict Transport Security)
    SECURE_HSTS_SECONDS = 31536000  # 1 año
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    
else:
    print("\n" + "="*60)
    print("🔧 MODO DESARROLLO ACTIVADO")
    print("="*60)
    print(f"   DEBUG = {DEBUG}")
    print(f"   Base de datos: SQLite local")
    print(f"   Cache: Local Memory (LocMem)")
    print(f"   Timeout Cache: 300s (5 min)")
    print("="*60 + "\n")

# ==================== CONFIGURACIÓN DE CLOUDINARY ====================

import cloudinary
import cloudinary.uploader
import cloudinary.api

if IS_PRODUCTION:
    # ✅ PRODUCCIÓN: Usar variables de entorno (MÁS SEGURO)
    cloudinary.config(
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME', 'dwwfzxo3z'),
        api_key=os.environ.get('CLOUDINARY_API_KEY', '447784864842837'),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET', 'WH8t6i2L3ZJLic5mFNVEmq6PNig'),
        secure=True
    )
    
    CLOUDINARY_STORAGE = {
        'CLOUD_NAME': os.environ.get('CLOUDINARY_CLOUD_NAME', 'dwwfzxo3z'),
        'API_KEY': os.environ.get('CLOUDINARY_API_KEY', '447784864842837'),
        'API_SECRET': os.environ.get('CLOUDINARY_API_SECRET', 'WH8t6i2L3ZJLic5mFNVEmq6PNig')
    }
else:
    # ✅ DESARROLLO: Hardcoded (OK para dev)
    cloudinary.config(
        cloud_name='dwwfzxo3z',
        api_key='447784864842837',
        api_secret='WH8t6i2L3ZJLic5mFNVEmq6PNig',
        secure=True
    )
    
    CLOUDINARY_STORAGE = {
        'CLOUD_NAME': 'dwwfzxo3z',
        'API_KEY': '447784864842837',
        'API_SECRET': 'WH8t6i2L3ZJLic5mFNVEmq6PNig'
    }

# ==================== DEBUG TOOLBAR (OPCIONAL - SOLO DESARROLLO) ====================

# ✅ Descomentar para habilitar Django Debug Toolbar
# pip install django-debug-toolbar

if DEBUG and not IS_PRODUCTION:
    try:
        import debug_toolbar
        
        INSTALLED_APPS += ['debug_toolbar']
        MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')
        
        INTERNAL_IPS = [
            '127.0.0.1',
            'localhost',
        ]
        
        DEBUG_TOOLBAR_CONFIG = {
            'SHOW_TOOLBAR_CALLBACK': lambda request: DEBUG,
        }
        
        print("✅ Django Debug Toolbar habilitado")
        
    except ImportError:
        pass  # Debug toolbar no instalado, continuar sin él
