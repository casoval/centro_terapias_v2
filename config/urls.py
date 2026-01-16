# config/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('pacientes/', include('pacientes.urls')),
    path('agenda/', include('agenda.urls')),
    path('servicios/', include('servicios.urls')),
    path('profesionales/', include('profesionales.urls')),
    path('facturacion/', include('facturacion.urls')),
]

# ==================== DEBUG TOOLBAR ====================
# ✅ CRÍTICO: Agregar las URLs de Debug Toolbar
if settings.DEBUG:
    try:
        import debug_toolbar
        # ⚠️ IMPORTANTE: Debe ir ANTES de urlpatterns principales
        urlpatterns = [
            path('__debug__/', include('debug_toolbar.urls')),
        ] + urlpatterns
        
    except ImportError:
        pass  # Debug toolbar no instalado, continuar sin él

# ==================== ARCHIVOS ESTÁTICOS Y MEDIA ====================
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)