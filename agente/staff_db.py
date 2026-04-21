"""
agente/staff_db.py
Módulo central de identificación de staff por número de teléfono.

Resuelve QUIÉN es el que escribe y QUÉ agente le corresponde,
manejando todos los casos:
  - Roles combinados (profesional+recepcionista, profesional+gerente)
  - Jerarquía de roles (superusuario > gerente > combinado > individual)
  - Usuarios/profesionales inactivos → público
  - Pacientes inactivos → público

Retorna un dataclass StaffIdentificado con toda la info necesaria
para que cada agente construya su contexto.
"""

import logging
from dataclasses import dataclass, field

log = logging.getLogger('agente')


def _normalizar_tel(telefono: str) -> str:
    """Normaliza teléfono eliminando prefijo de país."""
    tel = telefono.strip().replace(' ', '').replace('-', '')
    if tel.startswith('+591'):
        tel = tel[4:]
    elif tel.startswith('591') and len(tel) > 9:
        tel = tel[3:]
    return tel


@dataclass
class StaffIdentificado:
    """
    Resultado de identificar quién escribió y qué agente usar.

    tipo_agente:  'superusuario' | 'gerente' | 'recepcionista' |
                  'profesional' | 'recepcionista_profesional' | None
    perfil:       instancia de PerfilUsuario (o None para superusuario)
    profesional:  instancia de Profesional (o None)
    sucursales:   QuerySet de sucursales propias (puede ser vacío)
    es_combinado: True si tiene rol profesional + recepcionista
    """
    tipo_agente:  str | None         = None
    perfil:       object             = None
    profesional:  object             = None
    sucursales:   object             = None   # QuerySet
    es_combinado: bool               = False
    nombre:       str                = ''


def identificar_staff(telefono: str) -> StaffIdentificado:
    """
    Identifica al staff por teléfono y devuelve StaffIdentificado.
    Si no es staff, retorna StaffIdentificado(tipo_agente=None).

    Orden de prioridad:
      1. StaffAgente en BD (superusuario registrado manualmente)
      2. PerfilUsuario con is_superuser=True
      3. PerfilUsuario activo con rol gerente
      4. PerfilUsuario activo con rol recepcionista + profesional (combinado)
      5. PerfilUsuario activo con rol recepcionista
      6. PerfilUsuario activo con rol profesional (via Profesional.telefono)
    """
    tel = _normalizar_tel(telefono)
    if not tel:
        return StaffIdentificado()

    # ── 1. StaffAgente (superusuario registrado manualmente) ──────────────────
    try:
        from agente.models import StaffAgente
        _, tipo = StaffAgente.buscar_por_telefono(telefono)
        if tipo == 'superusuario':
            log.info(f'[StaffDB] {tel} → Superusuario (StaffAgente)')
            return StaffIdentificado(tipo_agente='superusuario', nombre='Dueño')
    except Exception as e:
        log.error(f'[StaffDB] Error StaffAgente: {e}')

    # ── 2-6. Buscar en PerfilUsuario por teléfono ─────────────────────────────
    perfil = _buscar_perfil_por_telefono(tel)

    if perfil:
        # Verificar que el perfil está activo
        if not perfil.activo:
            log.info(f'[StaffDB] {tel} → Perfil inactivo, tratando como público')
            return StaffIdentificado()

        user = perfil.user

        # ── 2. Superusuario Django ────────────────────────────────────────────
        if user.is_superuser:
            nombre = user.get_full_name() or user.username
            log.info(f'[StaffDB] {tel} → Superusuario (is_superuser) — {nombre}')
            return StaffIdentificado(
                tipo_agente = 'superusuario',
                perfil      = perfil,
                nombre      = nombre,
            )

        rol = perfil.rol or ''

        # ── 3. Gerente ────────────────────────────────────────────────────────
        if rol == 'gerente':
            nombre = user.get_full_name() or user.username
            sucursales = perfil.sucursales.all()
            # Si también es profesional, incluir el objeto profesional
            prof = getattr(perfil, 'profesional', None)
            log.info(f'[StaffDB] {tel} → Gerente — {nombre}')
            return StaffIdentificado(
                tipo_agente = 'gerente',
                perfil      = perfil,
                profesional = prof,
                sucursales  = sucursales,
                nombre      = nombre,
            )

        # ── 4. Recepcionista + Profesional (combinado) ─────────────────────
        if rol == 'recepcionista':
            nombre     = user.get_full_name() or user.username
            sucursales = perfil.sucursales.all()
            prof       = getattr(perfil, 'profesional', None)

            # Verificar que el profesional vinculado esté activo
            if prof and not prof.activo:
                prof = None

            if prof:
                log.info(f'[StaffDB] {tel} → Recepcionista+Profesional (combinado) — {nombre}')
                return StaffIdentificado(
                    tipo_agente  = 'recepcionista_profesional',
                    perfil       = perfil,
                    profesional  = prof,
                    sucursales   = sucursales,
                    es_combinado = True,
                    nombre       = nombre,
                )
            else:
                log.info(f'[StaffDB] {tel} → Recepcionista — {nombre}')
                return StaffIdentificado(
                    tipo_agente = 'recepcionista',
                    perfil      = perfil,
                    sucursales  = sucursales,
                    nombre      = nombre,
                )

    # ── 5. Profesional (por Profesional.telefono) ─────────────────────────────
    prof = _buscar_profesional_por_telefono(tel)
    if prof:
        if not prof.activo:
            log.info(f'[StaffDB] {tel} → Profesional inactivo, tratando como público')
            return StaffIdentificado()

        # Verificar si tiene PerfilUsuario con rol superior
        try:
            perfil_prof = prof.perfil_usuario
            if perfil_prof and perfil_prof.activo:
                rol = perfil_prof.rol or ''
                if rol == 'gerente':
                    # Ya fue manejado arriba via teléfono de perfil
                    # pero por si el teléfono está solo en Profesional
                    nombre = perfil_prof.user.get_full_name() or perfil_prof.user.username
                    log.info(f'[StaffDB] {tel} → Gerente (via Profesional) — {nombre}')
                    return StaffIdentificado(
                        tipo_agente = 'gerente',
                        perfil      = perfil_prof,
                        profesional = prof,
                        sucursales  = perfil_prof.sucursales.all(),
                        nombre      = nombre,
                    )
        except Exception:
            pass

        nombre = f'{prof.nombre} {prof.apellido}'
        log.info(f'[StaffDB] {tel} → Profesional — {nombre}')
        return StaffIdentificado(
            tipo_agente = 'profesional',
            profesional = prof,
            sucursales  = prof.sucursales.all(),
            nombre      = nombre,
        )

    return StaffIdentificado()


def _buscar_perfil_por_telefono(tel: str):
    """Busca PerfilUsuario por teléfono normalizado."""
    try:
        from usuarios.models import PerfilUsuario
        # Buscar con y sin prefijos comunes
        for variante in [tel, f'591{tel}', f'+591{tel}']:
            perfil = PerfilUsuario.objects.filter(
                telefono=variante
            ).select_related('user', 'profesional').first()
            if perfil:
                return perfil
    except Exception as e:
        log.error(f'[StaffDB] Error buscando perfil: {e}')
    return None


def _buscar_profesional_por_telefono(tel: str):
    """Busca Profesional activo por teléfono."""
    try:
        from profesionales.models import Profesional
        for variante in [tel, f'591{tel}', f'+591{tel}']:
            prof = Profesional.objects.filter(
                telefono=variante, activo=True
            ).prefetch_related('sucursales').first()
            if prof:
                return prof
    except Exception as e:
        log.error(f'[StaffDB] Error buscando profesional: {e}')
    return None


def get_sucursal_ids(staff: StaffIdentificado) -> list[int]:
    """Retorna lista de IDs de sucursales del staff. Vacía = todas."""
    if not staff.sucursales:
        return []
    try:
        return list(staff.sucursales.values_list('id', flat=True))
    except Exception:
        return []


def get_nombre_sucursales(staff: StaffIdentificado) -> str:
    """Retorna nombres de sucursales como string legible."""
    if not staff.sucursales:
        return 'todas las sucursales'
    try:
        nombres = [s.nombre for s in staff.sucursales.all()]
        return ', '.join(nombres) if nombres else 'sin sucursal asignada'
    except Exception:
        return 'sin sucursal asignada'
