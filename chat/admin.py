from django.contrib import admin
from .models import Conversacion, Mensaje, NotificacionChat


@admin.register(Conversacion)
class ConversacionAdmin(admin.ModelAdmin):
    list_display = ['id', 'usuario_1', 'usuario_2', 'fecha_creacion', 'ultima_actualizacion', 'activa']
    list_filter = ['activa', 'fecha_creacion']
    search_fields = ['usuario_1__username', 'usuario_1__first_name', 'usuario_1__last_name',
                     'usuario_2__username', 'usuario_2__first_name', 'usuario_2__last_name']
    readonly_fields = ['fecha_creacion', 'ultima_actualizacion']
    date_hierarchy = 'fecha_creacion'
    
    fieldsets = (
        ('Participantes', {
            'fields': ('usuario_1', 'usuario_2')
        }),
        ('Estado', {
            'fields': ('activa',)
        }),
        ('Metadata', {
            'fields': ('fecha_creacion', 'ultima_actualizacion'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Mensaje)
class MensajeAdmin(admin.ModelAdmin):
    list_display = ['id', 'conversacion', 'remitente', 'contenido_preview', 'fecha_envio', 'leido']
    list_filter = ['leido', 'fecha_envio']
    search_fields = ['contenido', 'remitente__username', 'remitente__first_name', 'remitente__last_name']
    readonly_fields = ['fecha_envio', 'fecha_lectura']
    date_hierarchy = 'fecha_envio'
    
    fieldsets = (
        ('Mensaje', {
            'fields': ('conversacion', 'remitente', 'contenido')
        }),
        ('Estado de Lectura', {
            'fields': ('leido', 'fecha_lectura')
        }),
        ('Metadata', {
            'fields': ('fecha_envio',),
            'classes': ('collapse',)
        }),
    )
    
    def contenido_preview(self, obj):
        """Muestra una previsualización del contenido"""
        return obj.contenido[:50] + '...' if len(obj.contenido) > 50 else obj.contenido
    contenido_preview.short_description = 'Contenido'


@admin.register(NotificacionChat)
class NotificacionChatAdmin(admin.ModelAdmin):
    list_display = ['id', 'usuario', 'conversacion', 'mensaje_preview', 'leida', 'fecha_creacion']
    list_filter = ['leida', 'fecha_creacion']
    search_fields = ['usuario__username', 'usuario__first_name', 'usuario__last_name', 'mensaje__contenido']
    readonly_fields = ['fecha_creacion']
    date_hierarchy = 'fecha_creacion'
    
    fieldsets = (
        ('Notificación', {
            'fields': ('usuario', 'conversacion', 'mensaje')
        }),
        ('Estado', {
            'fields': ('leida',)
        }),
        ('Metadata', {
            'fields': ('fecha_creacion',),
            'classes': ('collapse',)
        }),
    )
    
    def mensaje_preview(self, obj):
        """Muestra una previsualización del mensaje"""
        contenido = obj.mensaje.contenido
        return contenido[:30] + '...' if len(contenido) > 30 else contenido
    mensaje_preview.short_description = 'Mensaje'