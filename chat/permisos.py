"""
Sistema de Permisos para Chat según Roles y Sucursales

Estructura:
- PACIENTE: Profesionales que lo atendieron + Staff de sus sucursales + Admin
- PROFESIONAL: Pacientes que atendió + Staff de sus sucursales + Admin
- RECEPCIONISTA: Pacientes/Profesionales de sus sucursales + Staff de sus sucursales + Admin
- GERENTE: Pacientes/Profesionales de sus sucursales + Recepcionistas + Otros gerentes + Admin
- ADMIN: TODOS
"""

from django.contrib.auth.models import User
from django.db.models import Q


def pueden_chatear(usuario1, usuario2):
    """
    ✅ FUNCIÓN PRINCIPAL - Verifica si dos usuarios pueden chatear entre sí
    
    Args:
        usuario1: Usuario que inicia el chat
        usuario2: Usuario destinatario
        
    Returns:
        bool: True si pueden chatear, False en caso contrario
    """
    
    # ==================== REGLA 1: ADMIN PUEDE CON TODOS ====================
    if usuario1.is_superuser or usuario2.is_superuser:
        return True
    
    # ==================== VERIFICAR QUE AMBOS TENGAN PERFIL ====================
    if not hasattr(usuario1, 'perfil') or not hasattr(usuario2, 'perfil'):
        return False
    
    perfil1 = usuario1.perfil
    perfil2 = usuario2.perfil
    
    # ==================== REGLA 2: PACIENTE ↔ OTRO ROL ====================
    if perfil1.es_paciente():
        return _paciente_puede_chatear_con(usuario1, usuario2, perfil2)
    
    if perfil2.es_paciente():
        return _paciente_puede_chatear_con(usuario2, usuario1, perfil1)
    
    # ==================== REGLA 3: PROFESIONAL ↔ STAFF ====================
    if perfil1.es_profesional():
        return _profesional_puede_chatear_con(usuario1, usuario2, perfil2)
    
    if perfil2.es_profesional():
        return _profesional_puede_chatear_con(usuario2, usuario1, perfil1)
    
    # ==================== REGLA 4: STAFF ↔ STAFF ====================
    if perfil1.es_recepcionista() or perfil1.es_gerente():
        if perfil2.es_recepcionista() or perfil2.es_gerente():
            return _staff_puede_chatear_con_staff(perfil1, perfil2)
    
    # Si no cumple ninguna regla, NO pueden chatear
    return False


# ========================================================================
# FUNCIONES AUXILIARES PARA CADA ROL
# ========================================================================

def _paciente_puede_chatear_con(paciente_user, otro_user, otro_perfil):
    """
    ✅ PACIENTE puede chatear con:
    - Profesionales que lo han atendido (tienen sesiones)
    - Recepcionistas de sus sucursales
    - Gerentes de sus sucursales
    - Admin
    """
    
    # ✅ Verificar que el paciente tenga registro de Paciente
    if not hasattr(paciente_user, 'paciente'):
        return False
    
    paciente = paciente_user.paciente
    
    # ==================== PACIENTE ↔ PROFESIONAL ====================
    if otro_perfil.es_profesional():
        if not hasattr(otro_user, 'profesional'):
            return False
        
        profesional = otro_user.profesional
        
        # Verificar si tiene sesiones con este profesional
        from agenda.models import Sesion
        tiene_sesiones = Sesion.objects.filter(
            paciente=paciente,
            profesional=profesional
        ).exists()
        
        return tiene_sesiones
    
    # ==================== PACIENTE ↔ RECEPCIONISTA ====================
    if otro_perfil.es_recepcionista():
        # Obtener sucursales del paciente
        sucursales_paciente = paciente.sucursales.all()
        
        # Obtener sucursales del recepcionista
        sucursales_recepcionista = otro_perfil.sucursales.all()
        
        # Verificar si comparten al menos una sucursal
        return sucursales_paciente.filter(
            id__in=sucursales_recepcionista
        ).exists()
    
    # ==================== PACIENTE ↔ GERENTE ====================
    if otro_perfil.es_gerente():
        # Obtener sucursales del paciente
        sucursales_paciente = paciente.sucursales.all()
        
        # Obtener sucursales del gerente
        sucursales_gerente = otro_perfil.sucursales.all()
        
        # Verificar si comparten al menos una sucursal
        return sucursales_paciente.filter(
            id__in=sucursales_gerente
        ).exists()
    
    return False


def _profesional_puede_chatear_con(profesional_user, otro_user, otro_perfil):
    """
    ✅ PROFESIONAL puede chatear con:
    - Pacientes que ha atendido (tienen sesiones)
    - Otros profesionales de sus sucursales
    - Recepcionistas de sus sucursales
    - Gerentes de sus sucursales
    - Admin
    """
    
    # ✅ Verificar que el profesional tenga registro de Profesional
    if not hasattr(profesional_user, 'profesional'):
        return False
    
    profesional = profesional_user.profesional
    
    # ==================== PROFESIONAL ↔ PACIENTE ====================
    if otro_perfil.es_paciente():
        if not hasattr(otro_user, 'paciente'):
            return False
        
        paciente = otro_user.paciente
        
        # Verificar si tiene sesiones con este paciente
        from agenda.models import Sesion
        tiene_sesiones = Sesion.objects.filter(
            paciente=paciente,
            profesional=profesional
        ).exists()
        
        return tiene_sesiones
    
    # ==================== PROFESIONAL ↔ PROFESIONAL ====================
    if otro_perfil.es_profesional():
        if not hasattr(otro_user, 'profesional'):
            return False
        
        otro_profesional = otro_user.profesional
        
        # Obtener sucursales de ambos profesionales
        sucursales_profesional = profesional.sucursales.all()
        sucursales_otro_profesional = otro_profesional.sucursales.all()
        
        # Verificar si comparten al menos una sucursal
        return sucursales_profesional.filter(
            id__in=sucursales_otro_profesional
        ).exists()
    
    # ==================== PROFESIONAL ↔ RECEPCIONISTA ====================
    if otro_perfil.es_recepcionista():
        # Obtener sucursales del profesional
        sucursales_profesional = profesional.sucursales.all()
        
        # Obtener sucursales del recepcionista
        sucursales_recepcionista = otro_perfil.sucursales.all()
        
        # Verificar si comparten al menos una sucursal
        return sucursales_profesional.filter(
            id__in=sucursales_recepcionista
        ).exists()
    
    # ==================== PROFESIONAL ↔ GERENTE ====================
    if otro_perfil.es_gerente():
        # Obtener sucursales del profesional
        sucursales_profesional = profesional.sucursales.all()
        
        # Obtener sucursales del gerente
        sucursales_gerente = otro_perfil.sucursales.all()
        
        # Verificar si comparten al menos una sucursal
        return sucursales_profesional.filter(
            id__in=sucursales_gerente
        ).exists()
    
    return False


def _staff_puede_chatear_con_staff(perfil1, perfil2):
    """
    ✅ STAFF (Recepcionista/Gerente) puede chatear con STAFF:
    - Recepcionista ↔ Recepcionista: Mismo sucursal
    - Recepcionista ↔ Gerente: Misma sucursal
    - Gerente ↔ Gerente: TODOS entre sí
    """
    
    # ==================== GERENTE ↔ GERENTE ====================
    if perfil1.es_gerente() and perfil2.es_gerente():
        # Todos los gerentes pueden chatear entre sí
        return True
    
    # ==================== OTROS CASOS DE STAFF ====================
    # Obtener sucursales de ambos
    sucursales1 = perfil1.sucursales.all()
    sucursales2 = perfil2.sucursales.all()
    
    # Verificar si comparten al menos una sucursal
    return sucursales1.filter(id__in=sucursales2).exists()


# ========================================================================
# FUNCIONES AUXILIARES PARA VISTAS
# ========================================================================

def get_usuarios_disponibles_para_chat(usuario_actual):
    """
    ✅ Obtiene la lista de usuarios con los que puede chatear el usuario actual
    AGRUPADOS POR ROL para mejor UX
    
    Returns:
        dict: {
            'pacientes': [...],
            'profesionales': [...],
            'recepcionistas': [...],
            'gerentes': [...],
            'admins': [...]
        }
    """
    
    usuarios_disponibles = {
        'pacientes': [],
        'profesionales': [],
        'recepcionistas': [],
        'gerentes': [],
        'admins': []
    }
    
    # Si es superadmin, puede chatear con TODOS
    if usuario_actual.is_superuser:
        todos_usuarios = User.objects.exclude(id=usuario_actual.id).select_related('perfil')
        
        for user in todos_usuarios:
            if user.is_superuser:
                usuarios_disponibles['admins'].append(user)
            elif hasattr(user, 'perfil'):
                if user.perfil.es_paciente():
                    usuarios_disponibles['pacientes'].append(user)
                elif user.perfil.es_profesional():
                    usuarios_disponibles['profesionales'].append(user)
                elif user.perfil.es_recepcionista():
                    usuarios_disponibles['recepcionistas'].append(user)
                elif user.perfil.es_gerente():
                    usuarios_disponibles['gerentes'].append(user)
        
        return usuarios_disponibles
    
    # Para usuarios normales, verificar uno por uno
    if not hasattr(usuario_actual, 'perfil'):
        return usuarios_disponibles
    
    perfil_actual = usuario_actual.perfil
    
    # ==================== PACIENTE ====================
    if perfil_actual.es_paciente():
        # Profesionales que lo han atendido
        from agenda.models import Sesion
        from profesionales.models import Profesional
        
        paciente = usuario_actual.paciente
        profesionales_ids = Sesion.objects.filter(
            paciente=paciente
        ).values_list('profesional__user_id', flat=True).distinct()
        
        usuarios_disponibles['profesionales'] = User.objects.filter(
            id__in=profesionales_ids
        )
        
        # Staff de sus sucursales
        sucursales_paciente = paciente.sucursales.all()
        
        # Recepcionistas
        usuarios_disponibles['recepcionistas'] = User.objects.filter(
            perfil__rol='recepcionista',
            perfil__sucursales__in=sucursales_paciente
        ).distinct()
        
        # Gerentes
        usuarios_disponibles['gerentes'] = User.objects.filter(
            perfil__rol='gerente',
            perfil__sucursales__in=sucursales_paciente
        ).distinct()
        
        # Admins
        usuarios_disponibles['admins'] = User.objects.filter(is_superuser=True)
    
    # ==================== PROFESIONAL ====================
    elif perfil_actual.es_profesional():
        from agenda.models import Sesion
        from pacientes.models import Paciente
        
        profesional = usuario_actual.profesional
        
        # Pacientes que ha atendido
        pacientes_ids = Sesion.objects.filter(
            profesional=profesional
        ).values_list('paciente__user_id', flat=True).distinct()
        
        usuarios_disponibles['pacientes'] = User.objects.filter(
            id__in=pacientes_ids
        ).exclude(id__isnull=True)
        
        # ✅ NUEVO: Otros profesionales de sus sucursales
        sucursales_profesional = profesional.sucursales.all()
        
        from profesionales.models import Profesional
        otros_profesionales_ids = Profesional.objects.filter(
            sucursales__in=sucursales_profesional,
            user__isnull=False
        ).exclude(
            user_id=usuario_actual.id
        ).values_list('user_id', flat=True).distinct()
        
        usuarios_disponibles['profesionales'] = User.objects.filter(id__in=otros_profesionales_ids)
        
        # Staff de sus sucursales
        
        # Recepcionistas
        usuarios_disponibles['recepcionistas'] = User.objects.filter(
            perfil__rol='recepcionista',
            perfil__sucursales__in=sucursales_profesional
        ).distinct()
        
        # Gerentes
        usuarios_disponibles['gerentes'] = User.objects.filter(
            perfil__rol='gerente',
            perfil__sucursales__in=sucursales_profesional
        ).distinct()
        
        # Admins
        usuarios_disponibles['admins'] = User.objects.filter(is_superuser=True)
    
    # ==================== RECEPCIONISTA ====================
    elif perfil_actual.es_recepcionista():
        sucursales_recepcionista = perfil_actual.sucursales.all()
        
        # Pacientes de sus sucursales
        from pacientes.models import Paciente
        pacientes_ids = Paciente.objects.filter(
            sucursales__in=sucursales_recepcionista,
            user__isnull=False
        ).values_list('user_id', flat=True).distinct()
        
        usuarios_disponibles['pacientes'] = User.objects.filter(id__in=pacientes_ids)
        
        # Profesionales de sus sucursales
        from profesionales.models import Profesional
        profesionales_ids = Profesional.objects.filter(
            sucursales__in=sucursales_recepcionista,
            user__isnull=False
        ).values_list('user_id', flat=True).distinct()
        
        usuarios_disponibles['profesionales'] = User.objects.filter(id__in=profesionales_ids)
        
        # Otros recepcionistas de sus sucursales
        usuarios_disponibles['recepcionistas'] = User.objects.filter(
            perfil__rol='recepcionista',
            perfil__sucursales__in=sucursales_recepcionista
        ).exclude(id=usuario_actual.id).distinct()
        
        # Gerentes de sus sucursales
        usuarios_disponibles['gerentes'] = User.objects.filter(
            perfil__rol='gerente',
            perfil__sucursales__in=sucursales_recepcionista
        ).distinct()
        
        # Admins
        usuarios_disponibles['admins'] = User.objects.filter(is_superuser=True)
    
    # ==================== GERENTE ====================
    elif perfil_actual.es_gerente():
        sucursales_gerente = perfil_actual.sucursales.all()
        
        # Pacientes de sus sucursales
        from pacientes.models import Paciente
        pacientes_ids = Paciente.objects.filter(
            sucursales__in=sucursales_gerente,
            user__isnull=False
        ).values_list('user_id', flat=True).distinct()
        
        usuarios_disponibles['pacientes'] = User.objects.filter(id__in=pacientes_ids)
        
        # Profesionales de sus sucursales
        from profesionales.models import Profesional
        profesionales_ids = Profesional.objects.filter(
            sucursales__in=sucursales_gerente,
            user__isnull=False
        ).values_list('user_id', flat=True).distinct()
        
        usuarios_disponibles['profesionales'] = User.objects.filter(id__in=profesionales_ids)
        
        # Recepcionistas de sus sucursales
        usuarios_disponibles['recepcionistas'] = User.objects.filter(
            perfil__rol='recepcionista',
            perfil__sucursales__in=sucursales_gerente
        ).distinct()
        
        # TODOS los gerentes
        usuarios_disponibles['gerentes'] = User.objects.filter(
            perfil__rol='gerente'
        ).exclude(id=usuario_actual.id)
        
        # Admins
        usuarios_disponibles['admins'] = User.objects.filter(is_superuser=True)
    
    return usuarios_disponibles