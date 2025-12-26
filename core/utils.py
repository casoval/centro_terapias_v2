"""
Utilidades para gestión de permisos y filtros por sucursal
✅ Sistema completo de permisos por roles
"""
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from profesionales.models import Profesional


# ====================================
# FUNCIONES AUXILIARES
# ====================================

def get_perfil_usuario(user):
    """Obtiene el perfil del usuario"""
    if user.is_superuser:
        return None  # Superuser no necesita perfil
    
    if hasattr(user, 'perfil'):
        return user.perfil
    
    # Crear perfil si no existe
    from core.models import PerfilUsuario
    perfil, created = PerfilUsuario.objects.get_or_create(user=user)
    return perfil


def get_sucursales_usuario(user):
    """
    Obtiene las sucursales del usuario actual.
    
    Returns:
        - None si es superuser (puede ver todas)
        - QuerySet de Sucursales según el rol
        - QuerySet vacío si no tiene perfil o sucursales
    """
    if user.is_superuser:
        return None  # Superuser ve todas
    
    perfil = get_perfil_usuario(user)
    
    if not perfil or not perfil.rol:
        from servicios.models import Sucursal
        return Sucursal.objects.none()
    
    return perfil.get_sucursales()


def get_profesional_usuario(user):
    """
    Obtiene el objeto Profesional asociado al usuario actual.
    """
    perfil = get_perfil_usuario(user)
    if perfil and perfil.profesional:
        return perfil.profesional
    
    # Fallback: buscar por relación directa (compatibilidad)
    try:
        return Profesional.objects.get(user=user)
    except Profesional.DoesNotExist:
        return None


def filtrar_por_sucursales(queryset, user):
    """
    Filtra un queryset por las sucursales del usuario.
    """
    sucursales = get_sucursales_usuario(user)
    
    if sucursales is None:
        # Superuser: retornar todo
        return queryset
    
    if not sucursales.exists():
        # Sin sucursales: retornar vacío
        return queryset.none()
    
    # Filtrar por sucursales del usuario
    if hasattr(queryset.model, 'sucursales'):
        return queryset.filter(sucursales__in=sucursales).distinct()
    elif hasattr(queryset.model, 'sucursal'):
        return queryset.filter(sucursal__in=sucursales).distinct()
    
    return queryset


def puede_ver_sucursal(user, sucursal):
    """
    Verifica si un usuario puede ver datos de una sucursal específica.
    """
    if user.is_superuser:
        return True
    
    perfil = get_perfil_usuario(user)
    if perfil:
        return perfil.tiene_acceso_sucursal(sucursal)
    
    return False


# ====================================
# DECORADORES DE PERMISOS
# ====================================

def requiere_perfil(view_func):
    """
    Decorador que requiere que el usuario tenga un perfil válido con rol.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        
        perfil = get_perfil_usuario(request.user)
        
        if not perfil or not perfil.rol:
            messages.error(
                request,
                '⚠️ Tu cuenta no tiene un rol asignado. Contacta al administrador.'
            )
            return redirect('core:dashboard')
        
        # Adjuntar perfil al request
        request.perfil = perfil
        request.sucursales_usuario = perfil.get_sucursales()
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


def requiere_profesional(view_func):
    """
    Decorador que requiere que el usuario sea un profesional.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        
        perfil = get_perfil_usuario(request.user)
        
        if not perfil or not perfil.es_profesional():
            messages.error(
                request,
                '⚠️ Esta función es solo para profesionales.'
            )
            return redirect('core:dashboard')
        
        profesional = perfil.profesional
        if not profesional:
            messages.error(
                request,
                '⚠️ No tienes un perfil de profesional vinculado.'
            )
            return redirect('core:dashboard')
        
        # Adjuntar al request
        request.perfil = perfil
        request.profesional = profesional
        request.sucursales_usuario = profesional.sucursales.all()
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


def requiere_permiso(permiso_method):
    """
    Decorador genérico para verificar permisos.
    
    Uso: @requiere_permiso('puede_crear_pacientes')
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            
            perfil = get_perfil_usuario(request.user)
            
            if not perfil:
                raise PermissionDenied("No tienes permiso para esta acción.")
            
            # Verificar permiso
            tiene_permiso = getattr(perfil, permiso_method, lambda: False)()
            
            if not tiene_permiso:
                messages.error(
                    request,
                    '⚠️ No tienes permiso para realizar esta acción.'
                )
                return redirect('core:dashboard')
            
            request.perfil = perfil
            request.sucursales_usuario = perfil.get_sucursales()
            
            return view_func(request, *args, **kwargs)
        
        return wrapper
    return decorator


def solo_sus_sucursales(view_func):
    """
    Decorador que filtra automáticamente por las sucursales del usuario.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        sucursales = get_sucursales_usuario(request.user)
        request.sucursales_usuario = sucursales
        
        if not request.user.is_superuser:
            request.perfil = get_perfil_usuario(request.user)
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


# Decoradores específicos para acciones comunes
puede_crear_pacientes = lambda f: requiere_permiso('puede_crear_pacientes')(f)
puede_crear_sesiones = lambda f: requiere_permiso('puede_crear_sesiones')(f)
puede_crear_proyectos = lambda f: requiere_permiso('puede_crear_proyectos')(f)
puede_registrar_pagos = lambda f: requiere_permiso('puede_registrar_pagos')(f)
puede_crear_servicios = lambda f: requiere_permiso('puede_crear_servicios')(f)
puede_crear_profesionales = lambda f: requiere_permiso('puede_crear_profesionales')(f)
puede_crear_sucursales = lambda f: requiere_permiso('puede_crear_sucursales')(f)
puede_eliminar_sesiones = lambda f: requiere_permiso('puede_eliminar_sesiones')(f)
puede_eliminar_proyectos = lambda f: requiere_permiso('puede_eliminar_proyectos')(f)
puede_anular_pagos = lambda f: requiere_permiso('puede_anular_pagos')(f)
puede_ver_reportes = lambda f: requiere_permiso('puede_ver_reportes')(f)


# ====================================
# MIXINS PARA VISTAS BASADAS EN CLASES
# ====================================

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.base import ContextMixin


class PerfilRequiredMixin(LoginRequiredMixin):
    """
    Mixin que requiere que el usuario tenga perfil con rol.
    """
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        
        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        
        perfil = get_perfil_usuario(request.user)
        
        if not perfil or not perfil.rol:
            messages.error(
                request,
                '⚠️ Tu cuenta no tiene un rol asignado.'
            )
            return redirect('core:dashboard')
        
        # Adjuntar al request
        request.perfil = perfil
        request.sucursales_usuario = perfil.get_sucursales()
        
        return super().dispatch(request, *args, **kwargs)


class SucursalMixin(ContextMixin):
    """
    Mixin para vistas basadas en clases que filtra por sucursales del usuario.
    """
    
    def get_queryset(self):
        qs = super().get_queryset()
        return filtrar_por_sucursales(qs, self.request.user)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sucursales_usuario'] = get_sucursales_usuario(self.request.user)
        
        if not self.request.user.is_superuser:
            context['perfil'] = get_perfil_usuario(self.request.user)
        
        return context


class ProfesionalRequiredMixin(LoginRequiredMixin):
    """
    Mixin que requiere que el usuario sea profesional.
    """
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        
        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        
        perfil = get_perfil_usuario(request.user)
        
        if not perfil or not perfil.es_profesional():
            messages.error(request, '⚠️ Acceso solo para profesionales.')
            return redirect('core:dashboard')
        
        profesional = perfil.profesional
        if not profesional:
            messages.error(request, '⚠️ No tienes perfil de profesional vinculado.')
            return redirect('core:dashboard')
        
        # Adjuntar al request
        request.perfil = perfil
        request.profesional = profesional
        request.sucursales_usuario = profesional.sucursales.all()
        
        return super().dispatch(request, *args, **kwargs)


class PermisoMixin(LoginRequiredMixin):
    """
    Mixin genérico para verificar permisos.
    
    Uso: 
    class MiVista(PermisoMixin, View):
        permiso_requerido = 'puede_crear_pacientes'
    """
    permiso_requerido = None
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        
        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        
        if not self.permiso_requerido:
            raise ValueError("permiso_requerido no está definido en la vista")
        
        perfil = get_perfil_usuario(request.user)
        
        if not perfil:
            raise PermissionDenied("No tienes perfil asignado.")
        
        # Verificar permiso
        tiene_permiso = getattr(perfil, self.permiso_requerido, lambda: False)()
        
        if not tiene_permiso:
            messages.error(request, '⚠️ No tienes permiso para esta acción.')
            return redirect('core:dashboard')
        
        request.perfil = perfil
        request.sucursales_usuario = perfil.get_sucursales()
        
        return super().dispatch(request, *args, **kwargs)