from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
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
    """
    list_display = ('user', 'rol', 'get_sucursales', 'activo', 'fecha_creacion')
    list_filter = ('rol', 'activo', 'fecha_creacion')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'user__email')
    filter_horizontal = ('sucursales',)
    autocomplete_fields = ['user']
    
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
    
    def get_sucursales(self, obj):
        if obj.user.is_superuser:
            return 'TODAS (Superadmin)'
        sucursales = obj.get_sucursales()
        if sucursales is None:
            return 'Ninguna'
        count = sucursales.count()
        return f'{count} sucursal(es)' if count > 0 else 'Ninguna'
    get_sucursales.short_description = 'Sucursales'


# Re-registrar User con el admin personalizado
admin.site.unregister(User)
admin.site.register(User, UsuarioConPerfilAdmin)
