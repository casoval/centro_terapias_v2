from django.contrib import admin
from django.db import models
from django.forms import TextInput
from .models import Paciente, PacienteServicio

class PacienteServicioInline(admin.TabularInline):
    model = PacienteServicio
    extra = 1
    fields = ['servicio', 'costo_sesion', 'get_precio_base', 'activo', 'observaciones']
    readonly_fields = ['get_precio_base']
    
    def get_precio_base(self, obj):
        """Mostrar precio base del servicio como referencia"""
        if obj.servicio:
            return f"💡 Precio recomendado: Bs. {obj.servicio.costo_base}"
        return "Seleccione un servicio"
    get_precio_base.short_description = 'Precio Base'
    
    class Media:
        css = {
            'all': ('admin/css/paciente_servicio.css',)
        }
        js = ('admin/js/paciente_servicio.js',)

@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ['nombre_completo', 'get_sucursales', 'edad', 'parentesco', 'nombre_tutor', 'telefono_tutor', 'estado', 'fecha_registro']
    list_filter = ['estado', 'genero', 'parentesco', 'fecha_registro', 'sucursales']
    search_fields = ['nombre', 'apellido', 'nombre_tutor', 'telefono_tutor']
    filter_horizontal = ['sucursales']
    inlines = [PacienteServicioInline]
    
    fieldsets = (
        ('🏢 Sucursales', {
            'fields': ('sucursales',),
            'description': 'Sucursales donde puede ser atendido el paciente'
        }),
        ('👤 Información del Paciente', {
            'fields': ('nombre', 'apellido', 'fecha_nacimiento', 'genero')
        }),
        ('👨‍👩‍👧 Información del Tutor', {
            'fields': ('nombre_tutor', 'parentesco', 'telefono_tutor', 'email_tutor', 'direccion')
        }),
        ('🏥 Información Clínica', {
            'fields': ('diagnostico', 'observaciones_medicas', 'alergias')
        }),
        ('📊 Estado', {
            'fields': ('estado',)
        }),
    )
    
    def get_sucursales(self, obj):
        """Mostrar sucursales en el listado"""
        sucursales = obj.sucursales.all()
        if sucursales.count() == 0:
            return "❌ Sin sucursal"
        elif sucursales.count() == 1:
            return f"🏢 {sucursales.first().nombre}"
        else:
            return f"🏢 {sucursales.count()} sucursales"
    get_sucursales.short_description = 'Sucursales'

@admin.register(PacienteServicio)
class PacienteServicioAdmin(admin.ModelAdmin):
    list_display = ['paciente', 'servicio', 'costo_sesion', 'get_costo_base', 'get_diferencia', 'activo', 'fecha_inicio']
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
        if obj.servicio:
            diferencia = obj.costo_sesion - obj.servicio.costo_base if obj.costo_sesion else 0
            html = f"""
            <div style="padding: 10px; background: #f0f9ff; border-left: 4px solid #3b82f6; border-radius: 4px;">
                <p style="margin: 0; font-weight: bold;">💡 Precio recomendado base: Bs. {obj.servicio.costo_base}</p>
            """
            if diferencia > 0:
                html += f'<p style="margin: 5px 0 0 0; color: #059669;">✅ Precio personalizado: +Bs. {diferencia}</p>'
            elif diferencia < 0:
                html += f'<p style="margin: 5px 0 0 0; color: #dc2626;">⚠️ Descuento aplicado: Bs. {diferencia}</p>'
            else:
                html += '<p style="margin: 5px 0 0 0; color: #6b7280;">✓ Precio estándar</p>'
            html += '</div>'
            return html
        return "Seleccione un servicio primero"
    get_precio_base_info.short_description = 'Información de Precio'
    get_precio_base_info.allow_tags = True
    
    def get_costo_base(self, obj):
        """Mostrar costo base del servicio"""
        return f"Bs. {obj.servicio.costo_base}"
    get_costo_base.short_description = 'Precio Base'
    
    def get_diferencia(self, obj):
        """Mostrar diferencia con precio base"""
        if obj.costo_sesion and obj.servicio:
            diferencia = obj.costo_sesion - obj.servicio.costo_base
            if diferencia > 0:
                return f"✅ +Bs. {diferencia}"
            elif diferencia < 0:
                return f"⚠️ Bs. {diferencia}"
            else:
                return "✓ Estándar"
        return "-"
    get_diferencia.short_description = 'Diferencia'
    
    def save_model(self, request, obj, form, change):
        """Autocompletar costo_sesion si está vacío"""
        if not obj.costo_sesion and obj.servicio:
            obj.costo_sesion = obj.servicio.costo_base
        super().save_model(request, obj, form, change)