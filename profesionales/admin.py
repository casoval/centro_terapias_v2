from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import Profesional


@admin.register(Profesional)
class ProfesionalAdmin(admin.ModelAdmin):
    list_display = ['get_foto_thumbnail_admin', 'nombre_completo', 'get_sucursales', 
                    'especialidad', 'get_servicios', 'telefono', 'activo']
    list_filter = ['activo', 'especialidad', 'sucursales', 'servicios']
    search_fields = ['nombre', 'apellido', 'especialidad']
    filter_horizontal = ['servicios', 'sucursales']
    
    fieldsets = (
        ('📸 Foto del Profesional', {
            'fields': ('foto', 'get_foto_preview'),
            'description': 'Foto del profesional (se optimizará automáticamente)',
            'classes': ('collapse',)
        }),
        ('Sucursales', {
            'fields': ('sucursales',)
        }),
        ('Información Personal', {
            'fields': ('nombre', 'apellido', 'especialidad')
        }),
        ('Contacto', {
            'fields': ('telefono', 'email')
        }),
        ('Servicios que ofrece', {
            'fields': ('servicios',)
        }),
        ('Estado y Usuario', {
            'fields': ('activo', 'user')
        }),
    )
    
    readonly_fields = ['get_foto_preview']
    
    def get_foto_thumbnail_admin(self, obj):
        """Mostrar thumbnail en la lista de profesionales"""
        if not obj:
            return self._get_placeholder()
        
        if not obj.tiene_foto:
            return self._get_placeholder()
        
        try:
            foto_url = obj.get_foto_thumbnail()
            
            if foto_url and str(foto_url).strip():
                return format_html(
                    '<img src="{}" style="width: 40px; height: 40px; border-radius: 50%; '
                    'object-fit: cover; border: 2px solid #e5e7eb;" />',
                    foto_url
                )
        except Exception as e:
            print(f"Error cargando thumbnail: {e}")
        
        return self._get_placeholder()
    
    def _get_placeholder(self):
        """Retorna el HTML del placeholder"""
        return mark_safe(
            '<div style="width: 40px; height: 40px; border-radius: 50%; background: #e5e7eb; '
            'display: flex; align-items: center; justify-content: center; font-size: 18px;">👨‍⚕️</div>'
        )
    
    get_foto_thumbnail_admin.short_description = '📷'
    
    def get_foto_preview(self, obj):
        """Preview de la foto en el formulario de edición"""
        if not obj:
            return self._get_sin_foto_message()
        
        if not obj.tiene_foto:
            return self._get_sin_foto_message()
        
        try:
            foto_url = obj.get_foto_url()
            
            if foto_url and str(foto_url).strip():
                return format_html(
                    '<div style="margin-top: 10px;">'
                    '<p style="font-weight: bold; margin-bottom: 10px;">Vista Previa:</p>'
                    '<img src="{}" style="max-width: 300px; border-radius: 8px; border: 2px solid #e5e7eb;" />'
                    '<p style="margin-top: 10px; color: #6b7280; font-size: 12px;">'
                    'ℹ️ La imagen se optimiza automáticamente para web'
                    '</p>'
                    '</div>',
                    foto_url
                )
        except Exception as e:
            print(f"Error cargando preview: {e}")
            return mark_safe(
                '<p style="color: #ef4444;">⚠️ Error al cargar la imagen. Intenta subirla nuevamente.</p>'
            )
        
        return self._get_sin_foto_message()
    
    def _get_sin_foto_message(self):
        """Retorna el mensaje cuando no hay foto"""
        return mark_safe(
            '<p style="color: #9ca3af; font-style: italic;">Sin foto. Sube una imagen para verla aquí.</p>'
        )
    
    get_foto_preview.short_description = 'Vista Previa'
    
    def get_sucursales(self, obj):
        """Mostrar sucursales en el listado"""
        if not obj:
            return "—"
        
        sucursales = obj.sucursales.all()
        count = sucursales.count()
        
        if count == 0:
            return "❌ Sin sucursal"
        elif count == 1:
            return f"🏢 {sucursales.first().nombre}"
        else:
            return f"🏢 {count} sucursales"
    
    get_sucursales.short_description = 'Sucursales'
    
    def get_servicios(self, obj):
        """Mostrar servicios en el listado"""
        if not obj:
            return "—"
        
        servicios = obj.servicios.all()[:3]
        nombres = [s.nombre for s in servicios]
        
        if obj.servicios.count() > 3:
            nombres.append(f"(+{obj.servicios.count() - 3} más)")
        
        return ", ".join(nombres) if nombres else "Sin servicios"
    
    get_servicios.short_description = 'Servicios'