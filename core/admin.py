from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.contrib import messages
from .models import PerfilUsuario


class UsuarioConPerfilAdmin(BaseUserAdmin):
    """
    Admin de User que crea perfil automáticamente
    ✅ SIN INLINE para evitar problemas de M2M
    """
    list_display = ('username', 'email', 'first_name', 'last_name', 'get_rol', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'perfil__rol')
    
    def get_rol(self, obj):
        if obj.is_superuser:
            return '⭐ Super Admin'
        if hasattr(obj, 'perfil') and obj.perfil.rol:
            return obj.perfil.get_rol_display()
        return 'Sin rol'
    get_rol.short_description = 'Rol'
    
    def save_model(self, request, obj, form, change):
        """Crear perfil automáticamente al crear usuario"""
        from . import models as core_models
        
        # Desactivar signals
        core_models._disable_signals = True
        
        try:
            super().save_model(request, obj, form, change)
            
            # Crear perfil para usuarios no-superadmin
            if not obj.is_superuser:
                PerfilUsuario.objects.get_or_create(
                    user=obj,
                    defaults={'activo': True}
                )
        finally:
            core_models._disable_signals = False


@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    """
    Admin para gestionar perfiles de usuario
    ✅ Con validación de duplicados al vincular paciente
    """
    list_display = ('user', 'rol', 'get_vinculacion', 'get_sucursales', 'activo', 'fecha_creacion')
    list_filter = ('rol', 'activo', 'fecha_creacion')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'user__email')
    filter_horizontal = ('sucursales',)
    autocomplete_fields = ['user', 'profesional', 'paciente']
    
    fieldsets = (
        ('Usuario', {
            'fields': ('user',)
        }),
        ('Rol y Permisos', {
            'fields': ('rol', 'activo')
        }),
        ('Vinculación Profesional', {
            'fields': ('profesional',),
            'description': 'Solo para usuarios con rol de Profesional'
        }),
        ('✅ Vinculación Paciente', {
            'fields': ('paciente',),
            'description': '⚠️ IMPORTANTE: Si el paciente ya tiene cuenta creada automáticamente, no vincules otro usuario aquí'
        }),
        ('Sucursales Asignadas', {
            'fields': ('sucursales',),
            'description': 'Sucursales a las que tiene acceso (Recepcionistas y Gerentes)'
        }),
        ('Metadata', {
            'fields': ('fecha_creacion', 'fecha_modificacion'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ('fecha_creacion', 'fecha_modificacion')
    
    def get_vinculacion(self, obj):
        """✅ NUEVO: Mostrar vinculación con Profesional o Paciente"""
        if obj.profesional:
            return f'👨‍⚕️ {obj.profesional}'
        if obj.paciente:
            return f'👤 {obj.paciente}'
        return '-'
    get_vinculacion.short_description = 'Vinculación'
    
    def get_sucursales(self, obj):
        if obj.user.is_superuser:
            return 'TODAS (Superadmin)'
        if obj.es_paciente():
            return 'N/A (Paciente)'
        sucursales = obj.get_sucursales()
        if sucursales is None:
            return 'Ninguna'
        count = sucursales.count()
        return f'{count} sucursal(es)' if count > 0 else 'Ninguna'
    get_sucursales.short_description = 'Sucursales'
    
    def save_model(self, request, obj, form, change):
        """
        ✅ Validar antes de guardar para evitar duplicados
        """
        # Validar si se está asignando un paciente
        if obj.paciente:
            # Verificar si el paciente ya tiene otro perfil de usuario
            perfil_existente = PerfilUsuario.objects.filter(
                paciente=obj.paciente
            ).exclude(pk=obj.pk).first()
            
            if perfil_existente:
                messages.error(
                    request,
                    f'⚠️ ERROR: El paciente "{obj.paciente}" ya tiene una cuenta de usuario '
                    f'vinculada al usuario "{perfil_existente.user.username}". '
                    f'No puedes crear una segunda cuenta para el mismo paciente.'
                )
                return  # No guardar
            
            # Si está vinculando paciente, automáticamente poner rol paciente
            if not obj.rol or obj.rol != 'paciente':
                obj.rol = 'paciente'
                messages.info(
                    request,
                    '✅ Rol cambiado automáticamente a "Paciente" porque se vinculó un paciente.'
                )
        
        # Validar si se está asignando un profesional
        if obj.profesional:
            # Verificar si el profesional ya tiene otro perfil
            perfil_existente = PerfilUsuario.objects.filter(
                profesional=obj.profesional
            ).exclude(pk=obj.pk).first()
            
            if perfil_existente:
                messages.error(
                    request,
                    f'⚠️ ERROR: El profesional "{obj.profesional}" ya tiene una cuenta de usuario '
                    f'vinculada al usuario "{perfil_existente.user.username}". '
                    f'No puedes crear una segunda cuenta para el mismo profesional.'
                )
                return  # No guardar
            
            # Si está vinculando profesional, automáticamente poner rol profesional
            if not obj.rol or obj.rol != 'profesional':
                obj.rol = 'profesional'
                messages.info(
                    request,
                    '✅ Rol cambiado automáticamente a "Profesional" porque se vinculó un profesional.'
                )
        
        super().save_model(request, obj, form, change)


# Re-registrar User con el admin personalizado
admin.site.unregister(User)
admin.site.register(User, UsuarioConPerfilAdmin)