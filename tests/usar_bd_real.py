"""
Importar este módulo ANTES de hacer cualquier query Django redirige la
conexión de base de datos hacia la base PostgreSQL restaurada con el dump
real (centro_misael), en vez del sqlite de desarrollo.

Uso:
    import os, sys, django
    sys.path.append(os.getcwd())
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()
    import usar_bd_real  # <- después de django.setup(), antes de cualquier query
"""
from django.conf import settings
from django.db import connections

settings.DATABASES['default'] = {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': 'centro_terapias_restore',
    'USER': 'centro_user',
    'PASSWORD': 'centro_pass_local',
    'HOST': '127.0.0.1',
    'PORT': '5432',
    'CONN_MAX_AGE': 0,
}

# ConnectionHandler cachea dos cosas por separado, y ambas hay que invalidar:
# 1) `settings` (cached_property): el dict de DATABASES ya "configurado"
#    (con defaults aplicados) la primera vez que se accedió.
# 2) `_connections.default`: el DatabaseWrapper (sqlite) ya instanciado la
#    primera vez que se hizo una query — este no se actualiza solo aunque
#    cambiemos `settings.DATABASES`, hay que descartarlo explícitamente.
if 'settings' in connections.__dict__:
    del connections.__dict__['settings']
try:
    del connections['default']
except Exception:
    pass
connections.close_all()

print("⚡ Usando base de datos REAL restaurada: centro_terapias_restore (PostgreSQL)")
