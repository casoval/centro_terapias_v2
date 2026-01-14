"""
Django settings for config project.
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
    
    # CLOUDINARY - debe ir ANTES de django.contrib.staticfiles
    'cloudinary_storage',
    'cloudinary',
    
    'django.contrib.staticfiles',

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
            os.environ.get('DATABASE_URL')
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

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

# ⭐ WhiteNoise solo en producción
if IS_PRODUCTION:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
else:
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

# --------------------------------------------------
# MEDIA FILES
# --------------------------------------------------

MEDIA_URL = '/media/'

if IS_PRODUCTION:
    # ⭐ Cloudinary para archivos de media en producción
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
# CONFIGURACIONES ADICIONALES SEGÚN ENTORNO
# --------------------------------------------------

if IS_PRODUCTION:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
else:
    print("MODO DESARROLLO ACTIVADO")
    print(f"   DEBUG = {DEBUG}")
    print(f"   Base de datos: SQLite local")

# ==================== CONFIGURACIÓN DE CLOUDINARY ====================

import cloudinary
import cloudinary.uploader
import cloudinary.api

# ✅ CONFIGURACIÓN CORRECTA: usar cloudinary.config()
cloudinary.config(
    cloud_name='dwwfzxo3z',
    api_key='447784864842837',
    api_secret='WH8t6i2L3ZJLic5mFNVEmq6PNig',
    secure=True  # Usar HTTPS
)

# PARA PRODUCCIÓN (usar variables de entorno):
# cloudinary.config(
#     cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
#     api_key=os.environ.get('CLOUDINARY_API_KEY'),
#     api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
#     secure=True
# )

# ✅ Configuración para django-cloudinary-storage
CLOUDINARY_STORAGE = {
    'CLOUD_NAME': 'dwwfzxo3z',
    'API_KEY': '447784864842837',
    'API_SECRET': 'WH8t6i2L3ZJLic5mFNVEmq6PNig'
}