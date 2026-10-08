"""
marketing/guiones.py

Genera guiones con IA a partir de:
  - la marca (voz, reglas, contacto),
  - las FICHAS APROBADAS elegidas en la campaña (lo único que se puede afirmar),
  - datos de sede / profesional / servicio (vía `fuentes`),
  - los lineamientos de la campaña.

La salida de la IA nunca se confía: se normaliza, se valida con
`validadores.validar_guion` y, si falla, se intenta UNA reparación pasándole
los errores. Si sigue inválido se guarda como "rechazado" con sus errores
visibles. Un guion solo se puede aprobar si pasa la validación.
"""

import re

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from . import fuentes
from .models import AuditoriaMarketing, ConfigMarketing, Guion
from .proveedores.base import ProveedorError, extraer_json
from .proveedores.registro import obtener_proveedor_texto
from .validadores import MAX_DURACION_ESCENA, validar_guion

ENFOQUES = [
    'emocional y cercano (empieza conectando con una preocupación real de las familias)',
    'informativo y claro (empieza con una pregunta o dato útil que SÍ esté en las fichas)',
    'invitación directa (empieza con una invitación amable a conocer el servicio)',
]


class GuionError(Exception):
    """Error de uso (campaña mal configurada, sin fichas aprobadas, etc.)."""


# ── Contexto ────────────────────────────────────────────────────────────────

def construir_contexto(campana):
    marca = campana.marca
    fichas = list(campana.fichas.filter(aprobada=True, activa=True).order_by('titulo'))
    if not fichas:
        raise GuionError(
            'La campaña no tiene fichas APROBADAS seleccionadas. Aprueba al menos una ficha '
            '(Admin > Fichas de contenido) y asígnala a la campaña.'
        )

    sucursal = fuentes.datos_sucursal(campana.sucursal_id) if campana.sucursal_id else None
    profesional = fuentes.datos_profesional(campana.profesional_id) if campana.profesional_id else None
    servicio = fuentes.datos_tipo_servicio(campana.servicio_id, incluir_precio=marca.permite_precios) \
        if campana.servicio_id else None

    referencias = [
        {'nombre': a.nombre, 'tipo': a.tipo, 'descripcion': a.descripcion}
        for a in campana.activos_referencia.all() if a.usable_en_publicidad
    ]

    contactos = [c for c in [marca.whatsapp, (sucursal or {}).get('telefono')] if c]
    if not sucursal:
        contactos += [s['telefono'] for s in fuentes.datos_sucursales() if s['telefono']]

    return {
        'marca': {
            'nombre': marca.nombre, 'tono_voz': marca.tono_voz, 'reglas_contenido': marca.reglas_contenido,
            'palabras_prohibidas': marca.lista_palabras_prohibidas, 'permite_precios': marca.permite_precios,
            'cierre_fijo': marca.cierre_fijo, 'whatsapp': marca.whatsapp,
            'hashtags_base': marca.hashtags_base, 'lineamientos_base': marca.lineamientos_base,
        },
        'campana': {
            'titulo': campana.titulo, 'objetivo': campana.get_objetivo_display(),
            'origen_visual': campana.origen_visual, 'redes': campana.redes,
            'lineamientos': campana.lineamientos, 'notas': campana.notas,
        },
        'fichas': [{'titulo': f.titulo, 'texto': f.texto} for f in fichas],
        'sucursal': sucursal, 'profesional': profesional, 'servicio': servicio,
        'referencias': referencias,
        'contactos_permitidos': contactos,
    }


def _corpus(contexto):
    partes = [f['texto'] for f in contexto['fichas']]
    for k in ('sucursal', 'profesional', 'servicio'):
        if contexto.get(k):
            partes.append(' '.join(str(v) for v in contexto[k].values()))
    partes.append(contexto['marca']['cierre_fijo'])
    return '\n'.join(partes)


# ── Prompt ──────────────────────────────────────────────────────────────────

INSTRUCCIONES_SISTEMA = """Eres redactor de publicidad en español de Bolivia para una marca de niños y familias.
Escribes guiones cortos para redes sociales (Reels, TikTok, Facebook, Instagram).

REGLAS ABSOLUTAS:
1. Solo puedes afirmar lo que está en las FICHAS. Si algo no está en las fichas, no lo digas.
   No inventes cifras, porcentajes, años de experiencia, premios, cantidades de niños ni teléfonos.
2. No prometas curas ni resultados garantizados. No hagas diagnósticos ni des consejos médicos individuales.
3. No simules testimonios ni casos de pacientes/alumnos, ni uses "mi hijo".
4. Respeta el tono de la marca y las palabras prohibidas. Trata al público de "tú".
5. Los precios solo si la marca lo permite.
6. Los textos en pantalla son cortos (máximo 90 caracteres). El texto lo pone el editor de video:
   en prompt_visual NO pidas texto, letras, logos ni marcas dentro de la imagen.
7. El contacto debe ser el cierre fijo y/o los teléfonos de las fichas o la marca; no inventes otros.

Responde SOLO un objeto JSON válido, sin texto adicional, con esta forma exacta:
{
  "gancho": "frase de apertura (máx. 150 caracteres)",
  "escenas": [
    {"texto_pantalla": "texto corto", "locucion": "lo que se narra", "prompt_visual": "qué se ve", "duracion_seg": 4}
  ],
  "caption": "texto de la publicación",
  "hashtags": ["#uno", "#dos"]
}
"""


ETIQUETAS_LINEAMIENTOS = {
    'publico': 'Público objetivo', 'estilo_visual': 'Estilo visual', 'paleta': 'Paleta de colores',
    'mostrar': 'Debe mostrar', 'evitar': 'Debe evitar', 'llamada_accion': 'Llamada a la acción',
}


def _formatear_lineamientos(lineamientos):
    if not isinstance(lineamientos, dict) or not any(lineamientos.values()):
        return 'libres'
    return ' | '.join(
        f'{ETIQUETAS_LINEAMIENTOS.get(k, k)}: {v}' for k, v in lineamientos.items() if v
    )


def construir_prompt(contexto, enfoque, errores_previos=None, instrucciones_extra=''):
    m, c = contexto['marca'], contexto['campana']
    origen = {
        'propias': 'Se usarán FOTOS REALES del centro. En prompt_visual describe SOLO el movimiento de cámara '
                   'y el encuadre sobre una foto existente (ej: "zoom lento hacia la sala de terapia"); '
                   'no inventes escenas nuevas.',
        'referencia': 'Se usarán fotos propias como referencia visual. En prompt_visual describe el cambio o '
                      'ambientación que se quiere a partir de la foto, sin alterar productos reales.',
        'ia_total': 'Las imágenes las genera la IA. En prompt_visual describe la escena. Los niños deben ser '
                    'SIEMPRE en estilo ilustración, 3D o personaje de dibujo animado; NUNCA fotorrealistas.',
    }[c['origen_visual']]
    if c['origen_visual'] != 'propias' and ConfigMarketing.get().ia_permite_ninos_realistas:
        origen = origen.replace('NUNCA fotorrealistas', 'se permiten fotorrealistas solo si es imprescindible')

    fichas = '\n\n'.join(f'### {f["titulo"]}\n{f["texto"]}' for f in contexto['fichas'])
    extra = []
    for etiqueta, valor in (('Sede', contexto['sucursal']), ('Profesional', contexto['profesional']),
                            ('Servicio', contexto['servicio'])):
        if valor:
            extra.append(f'{etiqueta}: ' + '; '.join(f'{k}={v}' for k, v in valor.items() if k != 'id' and v))

    lineas = [
        f'MARCA: {m["nombre"]}',
        f'TONO DE VOZ: {m["tono_voz"] or "cálido y cercano"}',
        f'REGLAS DE CONTENIDO: {m["reglas_contenido"] or "ninguna adicional"}',
        f'PALABRAS PROHIBIDAS: {", ".join(m["palabras_prohibidas"]) or "ninguna"}',
        f'PRECIOS PERMITIDOS: {"sí" if m["permite_precios"] else "NO, no menciones precios ni costos"}',
        f'CIERRE FIJO (úsalo al final): {m["cierre_fijo"] or "sin cierre fijo"}',
        f'WHATSAPP: {m["whatsapp"] or "no definido (no inventes uno)"}',
        f'LINEAMIENTOS DE LA MARCA: {m["lineamientos_base"] or "ninguno"}',
        '',
        f'CAMPAÑA: {c["titulo"]}',
        f'OBJETIVO: {c["objetivo"]}',
        f'REDES DESTINO: {", ".join(c["redes"]) or "no definidas"}',
        f'LINEAMIENTOS DE LA CAMPAÑA: {_formatear_lineamientos(c["lineamientos"])}',
        f'NOTAS: {c["notas"] or "ninguna"}',
        f'ORIGEN VISUAL: {origen}',
    ]
    if contexto['referencias']:
        lineas.append('FOTOS/VIDEOS DE REFERENCIA DISPONIBLES: ' + '; '.join(
            f'{r["nombre"]} ({r["descripcion"] or r["tipo"]})' for r in contexto['referencias']))
    lineas += extra
    lineas += ['', 'FICHAS (única fuente de hechos permitida):', fichas, '',
               f'ENFOQUE PARA ESTE GUION: {enfoque}.',
               'Duración total objetivo: 20 a 35 segundos, de 4 a 7 escenas.']
    if instrucciones_extra:
        lineas.append(f'INSTRUCCIONES ADICIONALES DEL DUEÑO: {instrucciones_extra}')
    if errores_previos:
        lineas += ['', 'TU VERSIÓN ANTERIOR FUE RECHAZADA por estos problemas. Corrígelos TODOS:']
        lineas += [f'- ({e["campo"]}) {e["detalle"]}' for e in errores_previos]
    lineas.append('\nDevuelve únicamente el JSON.')
    return INSTRUCCIONES_SISTEMA, '\n'.join(lineas)


# ── Normalización ───────────────────────────────────────────────────────────

def _texto(valor, maximo=None):
    t = re.sub(r'[ \t]+', ' ', str(valor or '')).strip()
    return t[:maximo] if maximo else t


def normalizar_guion(crudo, marca):
    """Convierte la salida de la IA (o del usuario) a la forma interna, sin confiar en ella."""
    if not isinstance(crudo, dict):
        raise ProveedorError('La IA devolvió un formato inesperado.')
    escenas = []
    for e in (crudo.get('escenas') or []):
        if not isinstance(e, dict):
            continue
        try:
            dur = float(e.get('duracion_seg', 4))
        except (TypeError, ValueError):
            dur = 4.0
        dur = min(max(dur, 1.0), float(MAX_DURACION_ESCENA))
        escenas.append({
            'texto_pantalla': _texto(e.get('texto_pantalla')),
            'locucion': _texto(e.get('locucion')),
            'prompt_visual': _texto(e.get('prompt_visual')),
            'duracion_seg': round(dur, 1),
        })

    hashtags = crudo.get('hashtags') or []
    if isinstance(hashtags, str):
        hashtags = hashtags.split()
    vistos, finales = set(), []
    for h in list(hashtags) + marca.hashtags_base.split():
        h = '#' + re.sub(r'[^\w]', '', str(h).lstrip('#'))
        if len(h) > 1 and h.lower() not in vistos:
            vistos.add(h.lower())
            finales.append(h)

    return {
        'gancho': _texto(crudo.get('gancho')),
        'escenas': escenas,
        'caption': _texto(crudo.get('caption')),
        'hashtags': ' '.join(finales[:20]),
    }


def _validar(campana, contexto, guion):
    return validar_guion(
        guion, campana.marca, corpus_fuente=_corpus(contexto),
        contactos_permitidos=contexto['contactos_permitidos'],
        origen_visual=campana.origen_visual,
        permite_ninos_realistas=ConfigMarketing.get().ia_permite_ninos_realistas,
    )


# ── Persistencia ────────────────────────────────────────────────────────────

def _siguiente_version(campana):
    return (campana.guiones.aggregate(m=Max('version'))['m'] or 0) + 1


def _auditar(usuario, accion, guion, detalle=None):
    AuditoriaMarketing.objects.create(
        usuario=usuario, accion=accion, objeto_tipo='Guion', objeto_id=str(guion.pk), detalle=detalle or {},
    )


def _guardar(campana, contexto, guion, validacion, generado_por, proveedor_id='', modelo='', usuario=None):
    with transaction.atomic():
        g = Guion.objects.create(
            campana=campana, version=_siguiente_version(campana),
            estado='validado' if validacion['valido'] else 'rechazado',
            gancho=guion['gancho'], escenas=guion['escenas'], caption=guion['caption'],
            hashtags=guion['hashtags'], datos_fuente=contexto, validacion=validacion,
            generado_por=generado_por, proveedor_texto=proveedor_id, modelo_texto=modelo,
        )
        _auditar(usuario, 'guion_generado' if generado_por == 'ia' else 'guion_manual', g,
                 {'valido': validacion['valido'], 'errores': len(validacion['errores'])})
    return g


# ── API pública ─────────────────────────────────────────────────────────────

def generar_guiones(campana, cantidad=1, proveedor=None, usuario=None, instrucciones_extra=''):
    """
    Genera `cantidad` guiones (1–3), cada uno con un enfoque distinto.
    Devuelve la lista de Guion creados (válidos o rechazados, para que se vea el porqué).
    """
    if campana.quien_escribe == 'usuario':
        raise GuionError('Esta campaña está configurada para que TÚ escribas el texto. '
                         'Usa crear_guion_manual o cambia "Quién escribe".')
    cantidad = max(1, min(int(cantidad), len(ENFOQUES)))
    contexto = construir_contexto(campana)
    proveedor = proveedor or obtener_proveedor_texto()

    creados = []
    for i in range(cantidad):
        enfoque = ENFOQUES[i % len(ENFOQUES)]
        errores_previos = None
        guion = validacion = resp = None
        for intento in range(2):  # intento 0 = normal, 1 = reparación con los errores
            sistema, usuario_prompt = construir_prompt(contexto, enfoque, errores_previos, instrucciones_extra)
            try:
                resp = proveedor.generar(sistema, usuario_prompt)
                guion = normalizar_guion(extraer_json(resp.texto), campana.marca)
            except ProveedorError:
                if guion is not None:
                    break  # la reparación falló: nos quedamos con la primera versión (rechazada)
                if intento == 1:
                    raise
                continue
            validacion = _validar(campana, contexto, guion)
            if validacion['valido']:
                break
            errores_previos = validacion['errores']
        if guion is None:  # ni el intento ni la reparación dieron un JSON utilizable
            raise ProveedorError('La IA no devolvió un guion utilizable. Intenta de nuevo.')
        creados.append(_guardar(campana, contexto, guion, validacion, 'ia',
                                proveedor.id, getattr(resp, 'modelo', ''), usuario))
    return creados


def crear_guion_manual(campana, gancho, escenas, caption='', hashtags='', usuario=None):
    """El dueño escribe el guion; se valida igual que uno de IA."""
    contexto = construir_contexto(campana)
    guion = normalizar_guion(
        {'gancho': gancho, 'escenas': escenas, 'caption': caption, 'hashtags': hashtags}, campana.marca,
    )
    validacion = _validar(campana, contexto, guion)
    return _guardar(campana, contexto, guion, validacion, 'usuario', usuario=usuario)


def aprobar_guion(guion, usuario):
    """Revalida con las reglas ACTUALES de la marca antes de aprobar."""
    if guion.estado not in ('validado', 'aprobado'):
        raise GuionError('Solo se puede aprobar un guion que haya pasado la validación.')
    campana = guion.campana
    contexto = construir_contexto(campana)
    validacion = _validar(campana, contexto, {
        'gancho': guion.gancho, 'escenas': guion.escenas, 'caption': guion.caption, 'hashtags': guion.hashtags,
    })
    if not validacion['valido']:
        guion.estado = 'rechazado'
        guion.validacion = validacion
        guion.save(update_fields=['estado', 'validacion', 'actualizado'])
        raise GuionError('El guion ya no cumple las reglas actuales de la marca. Revisa sus errores.')
    guion.estado = 'aprobado'
    guion.validacion = validacion
    guion.save(update_fields=['estado', 'validacion', 'actualizado'])
    _auditar(usuario, 'guion_aprobado', guion, {'en': timezone.now().isoformat()})
    return guion
