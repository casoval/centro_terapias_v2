# config/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls', namespace='core')),
    path('pacientes/', include('pacientes.urls')),
    path('agenda/', include('agenda.urls')),
    path('servicios/', include('servicios.urls')),
    path('profesionales/', include('profesionales.urls')),
    path('facturacion/', include('facturacion.urls')),
    # ✅ CORREGIDO: agregado namespace='chat' para que {% url "chat:..." %} funcione
    path('chat/', include('chat.urls', namespace='chat')),
]

# ==================== DEBUG TOOLBAR ====================
if settings.DEBUG:
    try:
        import debug_toolbar
        urlpatterns = [
            path('__debug__/', include('debug_toolbar.urls')),
        ] + urlpatterns
    except ImportError:
        pass

# ==================== ARCHIVOS ESTÁTICOS Y MEDIA ====================
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)