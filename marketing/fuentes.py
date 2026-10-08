"""
marketing/fuentes.py

ÚNICO punto de la app `marketing` autorizado a leer de otras apps del
proyecto (servicios, profesionales, core.servicios_data). Un test automático
(tests/test_independencia.py) falla si cualquier otro archivo importa de ellas.

Principios:
  - SOLO LECTURA. Nunca escribe en esas apps.
  - Devuelve diccionarios simples (no instancias de modelos), listos para
    guardarse como instantánea en `Guion.datos_fuente`.
  - Mínimo necesario: no expone teléfono/email personal de profesionales,
    ni fotos (las fotos pasan por `Activo`, que exige autorización), ni
    precios (salvo que se pidan explícitamente con `incluir_precio=True`).
"""

from core.servicios_data import SERVICIOS_PUBLICOS
from profesionales.models import Profesional
from servicios.models import Sucursal, TipoServicio


# ── Páginas públicas de servicios (texto ya aprobado por el centro) ─────────

def listar_servicios_publicos():
    return [
        {'slug': s['slug'], 'nombre': s['nombre'], 'nombre_corto': s.get('nombre_corto', s['nombre']),
         'icono': s.get('icono', '')}
        for s in SERVICIOS_PUBLICOS.values()
    ]


def obtener_servicio_publico(slug):
    return SERVICIOS_PUBLICOS.get(slug)


def texto_ficha_servicio(servicio):
    """
    Arma el texto de una ficha a partir de una entrada de SERVICIOS_PUBLICOS.
    Se omiten a propósito los campos de SEO (title_tag, meta_description, h1).
    """
    partes = [f'SERVICIO: {servicio["nombre"]}']
    if servicio.get('intro'):
        partes.append(f'Resumen: {servicio["intro"]}')
    if servicio.get('para_quien'):
        partes.append(f'Para quién es: {servicio["para_quien"]}')
    if servicio.get('condiciones'):
        partes.append('Condiciones que atendemos:\n' + '\n'.join(f'- {c}' for c in servicio['condiciones']))
    if servicio.get('como_es_sesion'):
        partes.append(f'Cómo es una sesión: {servicio["como_es_sesion"]}')
    if servicio.get('faqs'):
        partes.append('Preguntas frecuentes:\n' + '\n'.join(
            f'P: {f["q"]}\nR: {f["a"]}' for f in servicio['faqs']
        ))
    return '\n\n'.join(partes)


def fichas_servicios_publicos():
    """Lista de {clave, titulo, texto, tipo} listas para sincronizar como fichas."""
    return [
        {'clave': s['slug'], 'titulo': s['nombre'], 'texto': texto_ficha_servicio(s), 'tipo': 'servicio'}
        for s in SERVICIOS_PUBLICOS.values()
    ]


# ── Sucursales ──────────────────────────────────────────────────────────────

def datos_sucursales(solo_activas=True):
    qs = Sucursal.objects.all()
    if solo_activas:
        qs = qs.filter(activa=True)
    return [
        {'id': s.pk, 'nombre': s.nombre, 'direccion': s.direccion.strip(), 'telefono': s.telefono}
        for s in qs.order_by('nombre')
    ]


def datos_sucursal(pk):
    s = Sucursal.objects.filter(pk=pk).first()
    if not s:
        return None
    return {'id': s.pk, 'nombre': s.nombre, 'direccion': s.direccion.strip(), 'telefono': s.telefono}


def texto_ficha_sedes():
    sedes = datos_sucursales()
    if not sedes:
        return ''
    lineas = ['SEDES DEL CENTRO:']
    for s in sedes:
        linea = f'- {s["nombre"]}: {s["direccion"]}'
        if s['telefono']:
            linea += f' (Tel/WhatsApp: {s["telefono"]})'
        lineas.append(linea)
    return '\n'.join(lineas)


# ── Profesionales (solo datos que ya son públicos en la presentación) ───────

def datos_profesional(pk):
    """
    Solo nombre y especialidad. NO se expone teléfono, email, usuario ni foto.
    Para mostrar a un profesional en un anuncio, su foto debe cargarse como
    `Activo` con autorización confirmada.
    """
    p = Profesional.objects.filter(pk=pk, activo=True).first()
    if not p:
        return None
    return {'id': p.pk, 'nombre_completo': p.nombre_completo, 'especialidad': p.especialidad}


def listar_profesionales():
    """Profesionales activos para un selector. Solo id, nombre y especialidad."""
    return [
        {'id': p.pk, 'nombre_completo': p.nombre_completo, 'especialidad': p.especialidad}
        for p in Profesional.objects.filter(activo=True).order_by('nombre', 'apellido')
    ]


# ── Tipos de servicio (catálogo interno) ────────────────────────────────────

def datos_tipo_servicio(pk, incluir_precio=False):
    t = TipoServicio.objects.filter(pk=pk, activo=True).first()
    if not t:
        return None
    datos = {
        'id': t.pk, 'nombre': t.nombre, 'descripcion': t.descripcion,
        'duracion_minutos': t.duracion_minutos,
    }
    if incluir_precio:
        datos['costo_base'] = str(t.costo_base)
        if t.precio_mensual is not None:
            datos['precio_mensual'] = str(t.precio_mensual)
        if t.precio_proyecto is not None:
            datos['precio_proyecto'] = str(t.precio_proyecto)
    return datos
