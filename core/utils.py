"""
Utilidades para gestión de permisos y filtros por sucursal
"""
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from profesionales.models import Profesional


def get_sucursales_usuario(user):
    """
    Obtiene las sucursales del usuario actual.
    
    Returns:
        - QuerySet de Sucursales si el usuario tiene un perfil de Profesional
        - None si es superuser (puede ver todas)
        - QuerySet vacío si no tiene perfil asociado
    """
    if user.is_superuser:
        return None  # Superuser ve todas las sucursales
    
    try:
        profesional = Profesional.objects.get(user=user)
        return profesional.sucursales.all()
    except Profesional.DoesNotExist:
        from servicios.models import Sucursal
        return Sucursal.objects.none()


def get_profesional_usuario(user):
    """
    Obtiene el objeto Profesional asociado al usuario actual.
    
    Returns:
        - Profesional si existe
        - None si no existe
    """
    try:
        return Profesional.objects.get(user=user)
    except Profesional.DoesNotExist:
        return None


def filtrar_por_sucursales(queryset, user):
    """
    Filtra un queryset por las sucursales del usuario.
    
    Args:
        queryset: QuerySet a filtrar
        user: Usuario actual
    
    Returns:
        QuerySet filtrado por sucursales del usuario, o sin filtrar si es superuser
    """
    sucursales = get_sucursales_usuario(user)
    
    if sucursales is None:
        # Superuser: retornar todo
        return queryset
    
    if not sucursales.exists():
        # Sin sucursales: retornar vacío
        return queryset.none()
    
    # Filtrar por sucursales del usuario
    # Detectar si el modelo tiene 'sucursales' (ManyToMany) o 'sucursal' (ForeignKey)
    if hasattr(queryset.model, 'sucursales'):
        return queryset.filter(sucursales__in=sucursales).distinct()
    elif hasattr(queryset.model, 'sucursal'):
        return queryset.filter(sucursal__in=sucursales).distinct()
    
    return queryset


def puede_ver_sucursal(user, sucursal):
    """
    Verifica si un usuario puede ver datos de una sucursal específica.
    
    Args:
        user: Usuario a verificar
        sucursal: Objeto Sucursal
    
    Returns:
        bool: True si puede ver, False si no
    """
    if user.is_superuser:
        return True
    
    sucursales_usuario = get_sucursales_usuario(user)
    
    if sucursales_usuario is None:
        return False
    
    return sucursales_usuario.filter(id=sucursal.id).exists()


# ====================================
# DECORADORES
# ====================================

def requiere_profesional(view_func):
    """
    Decorador que requiere que el usuario tenga un perfil de Profesional.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.is_superuser:
            # Superuser siempre tiene acceso
            return view_func(request, *args, **kwargs)
        
        profesional = get_profesional_usuario(request.user)
        
        if profesional is None:
            messages.error(
                request, 
                '⚠️ No tienes un perfil de profesional asignado. Contacta al administrador.'
            )
            return redirect('core:dashboard')
        
        # Adjuntar profesional al request para uso posterior
        request.profesional = profesional
        request.sucursales_usuario = profesional.sucursales.all()
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


def solo_sus_sucursales(view_func):
    """
    Decorador que filtra automáticamente por las sucursales del usuario.
    Adjunta 'sucursales_usuario' al request.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        sucursales = get_sucursales_usuario(request.user)
        request.sucursales_usuario = sucursales
        return view_func(request, *args, **kwargs)
    
    return wrapper


# ====================================
# MIXINS PARA VISTAS BASADAS EN CLASES
# ====================================

class SucursalMixin:
    """
    Mixin para vistas basadas en clases que filtra por sucursales del usuario.
    """
    
    def get_queryset(self):
        qs = super().get_queryset()
        return filtrar_por_sucursales(qs, self.request.user)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sucursales_usuario'] = get_sucursales_usuario(self.request.user)
        return context


class ProfesionalRequiredMixin:
    """
    Mixin que requiere que el usuario tenga perfil de Profesional.
    """
    
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        
        profesional = get_profesional_usuario(request.user)
        
        if profesional is None:
            messages.error(
                request,
                '⚠️ No tienes un perfil de profesional asignado.'
            )
            return redirect('core:dashboard')
        
        # Adjuntar al request
        request.profesional = profesional
        request.sucursales_usuario = profesional.sucursales.all()
        
        return super().dispatch(request, *args, **kwargs)