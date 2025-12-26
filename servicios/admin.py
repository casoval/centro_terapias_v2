from django.contrib import admin
from django import forms
from django.utils.safestring import mark_safe  # ← AGREGAR ESTE IMPORT
from .models import TipoServicio, Sucursal


class TipoServicioAdminForm(forms.ModelForm):
    """
    Formulario personalizado con selector de color
    """
    color = forms.CharField(
        max_length=7,
        widget=forms.TextInput(attrs={
            'type': 'color',  # ← Esto convierte el input en un selector de color HTML5
            'style': 'width: 60px; height: 40px; cursor: pointer;'
        }),
        help_text='Selecciona el color para el calendario',
        initial='#3B82F6'
    )
    
    class Meta:
        model = TipoServicio
        fields = '__all__'


@admin.register(TipoServicio)
class TipoServicioAdmin(admin.ModelAdmin):
    form = TipoServicioAdminForm  # ← Usar el formulario personalizado
    
    list_display = ['nombre', 'duracion_minutos', 'costo_base', 'color_preview', 'activo']
    list_filter = ['activo']
    search_fields = ['nombre']
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('nombre', 'descripcion', 'activo')
        }),
        ('Configuración', {
            'fields': ('duracion_minutos', 'costo_base', 'color')
        }),
    )
    
    def color_preview(self, obj):
        """
        Mostrar una vista previa del color en la lista
        """
        # ✅ USAR mark_safe() para que Django renderice el HTML
        return mark_safe(
            f'<div style="width: 30px; height: 30px; background-color: {obj.color}; '
            f'border: 2px solid #ccc; border-radius: 4px;"></div>'
        )
    
    color_preview.short_description = 'Color'


@admin.register(Sucursal)
class SucursalAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'telefono', 'activa']
    list_filter = ['activa']
    search_fields = ['nombre', 'direccion']