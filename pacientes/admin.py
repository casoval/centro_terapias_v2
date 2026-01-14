from django.contrib import admin
from django.db import models
from django.forms import Textarea
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import Paciente, PacienteServicio


class PacienteServicioInline(admin.TabularInline):
    model = PacienteServicio
    extra = 1
    fields = ['servicio', 'costo_sesion', 'activo', 'observaciones']
    
    formfield_overrides = {
        models.TextField: {
            'widget': Textarea(attrs={
                'rows': 2,
                'cols': 40,
                'style': 'width: 300px;'
            })
        },
    }

@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ['get_foto_thumbnail_admin', 'nombre_completo', 'get_sucursales', 
                    'edad', 'parentesco', 'nombre_tutor', 'telefono_tutor', 
                    'get_segundo_tutor', 'estado', 'fecha_registro']
    list_filter = ['estado', 'genero', 'parentesco', 'fecha_registro', 'sucursales']
    search_fields = ['nombre', 'apellido', 'nombre_tutor', 'telefono_tutor', 
                     'nombre_tutor_2', 'telefono_tutor_2']
    filter_horizontal = ['sucursales']
    inlines = [PacienteServicioInline]
    
    fieldsets = (
        ('🏢 Sucursales', {
            'fields': ('sucursales',),
            'description': 'Sucursales donde puede ser atendido el paciente'
        }),
        ('📸 Foto del Paciente', {
            'fields': ('foto', 'get_foto_preview'),
            'description': 'Foto del paciente (se optimizará automáticamente)',
            'classes': ('collapse',)
        }),
        ('👤 Información del Paciente', {
            'fields': ('nombre', 'apellido', 'fecha_nacimiento', 'genero')
        }),
        ('👨‍👩‍👧 Tutor Principal (Obligatorio)', {
            'fields': ('nombre_tutor', 'parentesco', 'telefono_tutor', 'email_tutor', 'direccion'),
            'description': 'Información del tutor principal o contacto primario'
        }),
        ('👥 Segundo Tutor / Contacto de Emergencia (Opcional)', {
            'fields': ('nombre_tutor_2', 'parentesco_2', 'telefono_tutor_2', 'email_tutor_2'),
            'description': 'Información del segundo tutor o contacto de emergencia (opcional)',
            'classes': ('collapse',)
        }),
        ('🥼 Información Clínica', {
            'fields': ('diagnostico', 'observaciones_medicas', 'alergias')
        }),
        ('📊 Estado', {
            'fields': ('estado',)
        }),
    )
    
    readonly_fields = ['get_foto_preview']
    
    def get_foto_thumbnail_admin(self, obj):
        """Mostrar thumbnail en la lista de pacientes"""
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
        """Retorna el HTML del placeholder - USA mark_safe porque no hay variables"""
        return mark_safe(
            '<div style="width: 40px; height: 40px; border-radius: 50%; background: #e5e7eb; '
            'display: flex; align-items: center; justify-content: center; font-size: 18px;">👤</div>'
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
        """Retorna el mensaje cuando no hay foto - USA mark_safe porque no hay variables"""
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
    
    def get_segundo_tutor(self, obj):
        """Mostrar si tiene segundo tutor registrado"""
        if not obj:
            return "—"
        
        if obj.tiene_segundo_tutor:
            return f"✅ {obj.nombre_tutor_2}"
        return "➖"
    
    get_segundo_tutor.short_description = '2do Tutor'


@admin.register(PacienteServicio)
class PacienteServicioAdmin(admin.ModelAdmin):
    list_display = ['paciente', 'servicio', 'costo_sesion', 'get_costo_base', 
                    'get_diferencia', 'activo', 'fecha_inicio']
    list_filter = ['activo', 'servicio']
    search_fields = ['paciente__nombre', 'paciente__apellido']
    
    fieldsets = (
        ('Paciente y Servicio', {
            'fields': ('paciente', 'servicio')
        }),
        ('💰 Costos', {
            'fields': ('costo_sesion', 'get_precio_base_info'),
            'description': 'El costo se autocompleta con el precio base del servicio, pero puede personalizarse'
        }),
        ('Estado', {
            'fields': ('activo', 'observaciones')
        }),
    )
    
    readonly_fields = ['get_precio_base_info']
    
    def get_precio_base_info(self, obj):
        """Mostrar información del precio base"""
        if not obj or not obj.servicio:
            return "Seleccione un servicio primero"
        
        diferencia = obj.costo_sesion - obj.servicio.costo_base if obj.costo_sesion else 0
        
        # Construir el HTML con format_html usando placeholders
        if diferencia > 0:
            mensaje_diferencia = format_html(
                '<p style="margin: 5px 0 0 0; color: #059669;">✅ Precio personalizado: +Bs. {}</p>',
                diferencia
            )
        elif diferencia < 0:
            mensaje_diferencia = format_html(
                '<p style="margin: 5px 0 0 0; color: #dc2626;">⚠️ Descuento aplicado: Bs. {}</p>',
                diferencia
            )
        else:
            mensaje_diferencia = mark_safe(
                '<p style="margin: 5px 0 0 0; color: #6b7280;">✓ Precio estándar</p>'
            )
        
        html = format_html(
            '<div style="padding: 10px; background: #f0f9ff; border-left: 4px solid #3b82f6; border-radius: 4px;">'
            '<p style="margin: 0; font-weight: bold;">💡 Precio recomendado base: Bs. {}</p>'
            '{}'
            '</div>',
            obj.servicio.costo_base,
            mensaje_diferencia
        )
        
        return html
    
    get_precio_base_info.short_description = 'Información de Precio'
    
    def get_costo_base(self, obj):
        """Mostrar costo base del servicio"""
        if obj and obj.servicio:
            return f"Bs. {obj.servicio.costo_base}"
        return "—"
    
    get_costo_base.short_description = 'Precio Base'
    
    def get_diferencia(self, obj):
        """Mostrar diferencia con precio base"""
        if not obj or not obj.costo_sesion or not obj.servicio:
            return "—"
        
        diferencia = obj.costo_sesion - obj.servicio.costo_base
        
        if diferencia > 0:
            return f"✅ +Bs. {diferencia}"
        elif diferencia < 0:
            return f"⚠️ Bs. {diferencia}"
        else:
            return "✓ Estándar"
    
    get_diferencia.short_description = 'Diferencia'
    
    def save_model(self, request, obj, form, change):
        """Autocompletar costo_sesion con el precio base si está vacío"""
        if not obj.costo_sesion and obj.servicio:
            obj.costo_sesion = obj.servicio.costo_base
        super().save_model(request, obj, form, change)