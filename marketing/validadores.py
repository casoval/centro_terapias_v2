"""
marketing/validadores.py

Validador de contenido de guiones. Determinista (sin IA): mismo guion, mismo
resultado. Devuelve errores (bloquean la aprobación) y advertencias (se
muestran pero no bloquean).

Reglas con ERROR:
  estructura         gancho vacío, sin escenas, duraciones o largos fuera de rango
  palabra_prohibida  alguna palabra de Marca.palabras_prohibidas
  precio             menciona precios/costos y la marca no lo permite
  telefono           número de contacto que NO está en las fuentes aprobadas
  cifra_no_respaldada porcentaje o cantidad de niños/pacientes/familias inventada
  testimonio         simula testimonios o casos de pacientes
  ninos_realistas    pide niños fotorrealistas generados con IA (si está apagado)

Reglas con ADVERTENCIA:
  cifra_dudosa       años/sesiones/otros números que no aparecen en las fuentes
"""

import re
import unicodedata

MAX_GANCHO = 150
MAX_ESCENAS = 12
MAX_TEXTO_PANTALLA = 90
MAX_DURACION_ESCENA = 15
MAX_DURACION_TOTAL = 90
MAX_CAPTION = 2200
MAX_HASHTAGS = 30

_PATRON_PRECIO = re.compile(
    r'(?<!\w)(precio|precios|costo|costos|cuesta|cuestan|tarifa|tarifas|bs|bs\.|bolivianos|usd|dolares)(?!\w)'
)
_PATRON_TESTIMONIO = re.compile(
    r'testimonio|caso de exito|historia real|'
    r'(?<!\w)mi (hijo|hija|nino|nina|bebe)(?!\w)|'
    r'(?<!\w)nuestros? (pacientes|ninos|ninas|padres) (dicen|cuentan|opinan|nos dicen)'
)
_PATRON_PORCENTAJE = re.compile(r'\d+(?:[.,]\d+)?\s?%')
_PATRON_CANTIDAD_FUERTE = re.compile(
    r'(?<![\w.,])(\d[\d.,]*)\s+(ninos|ninas|pacientes|familias|casos)(?!\w)'
)
_PATRON_CANTIDAD_DEBIL = re.compile(r'(?<![\w.,])(\d[\d.,]*)\s+(anos|sesiones|meses|semanas)(?!\w)')
_PATRON_TELEFONO = re.compile(r'(?<!\d)(?:\+?\d[\d\s\-]{5,}\d)(?!\d)')
_PATRON_NINO = re.compile(r'(nino|nina|ninos|ninas|bebe|bebes|infante|infantes|chico|chica|menor|menores)')
_PATRON_REALISTA = re.compile(r'(fotorreal|fotorrealista|hiperreal|realista|foto real|photorealistic|photo-realistic)')


def normalizar(texto):
    """Minúsculas y sin acentos (la ñ pasa a n)."""
    texto = unicodedata.normalize('NFKD', str(texto or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return texto.lower()


def patron_palabra_prohibida(palabra):
    """
    Regex (sobre texto ya normalizado) para una palabra/frase prohibida.

    - Tolera plural y género en la última palabra: "garantizado" también
      detecta "garantizada", "garantizados", "garantizadas"; "cura" detecta "curas".
    - Un asterisco final es un comodín explícito: "garantiz*" detecta cualquier
      palabra que empiece con "garantiz" (garantiza, garantizamos, garantizar...).
    - No detecta la palabra dentro de otra ("cura" no salta con "procura").
    """
    p = normalizar(palabra).strip()
    if p.endswith('*'):
        return rf'(?<!\w){re.escape(p[:-1])}\w*'
    if p.endswith(('o', 'a')):
        cuerpo = rf'{re.escape(p[:-1])}[oa]s?'
    elif p.endswith(('e', 'i', 'u')):
        cuerpo = rf'{re.escape(p)}s?'
    elif p.endswith('s'):
        cuerpo = re.escape(p)
    else:
        cuerpo = rf'{re.escape(p)}(?:es)?'
    return rf'(?<!\w){cuerpo}(?!\w)'


def _solo_digitos(texto):
    d = re.sub(r'\D', '', str(texto))
    return d[3:] if d.startswith('591') and len(d) > 8 else d


def _textos_publicos(guion):
    """(campo, texto) de todo lo que verá el público."""
    salida = [('gancho', guion.get('gancho', '')), ('caption', guion.get('caption', '')),
              ('hashtags', guion.get('hashtags', ''))]
    for i, e in enumerate(guion.get('escenas') or [], start=1):
        if isinstance(e, dict):
            salida.append((f'escena {i} (texto en pantalla)', e.get('texto_pantalla', '')))
            salida.append((f'escena {i} (locución)', e.get('locucion', '')))
    return salida


def validar_guion(guion, marca, corpus_fuente='', contactos_permitidos=(),
                  origen_visual='propias', permite_ninos_realistas=False):
    """
    guion: dict con gancho, escenas[{texto_pantalla, locucion, prompt_visual, duracion_seg}],
           caption, hashtags (str).
    corpus_fuente: texto de las fichas aprobadas (lo único que se puede afirmar).
    contactos_permitidos: teléfonos/WhatsApp válidos (marca + sedes).
    """
    errores, advertencias = [], []

    def err(regla, campo, detalle):
        errores.append({'regla': regla, 'campo': campo, 'detalle': detalle})

    def adv(regla, campo, detalle):
        advertencias.append({'regla': regla, 'campo': campo, 'detalle': detalle})

    # ── Estructura ──────────────────────────────────────────────────────────
    gancho = (guion.get('gancho') or '').strip()
    escenas = guion.get('escenas')
    if not gancho:
        err('estructura', 'gancho', 'El gancho (primeros segundos) está vacío.')
    elif len(gancho) > MAX_GANCHO:
        err('estructura', 'gancho', f'El gancho supera {MAX_GANCHO} caracteres.')

    if not isinstance(escenas, list) or not escenas:
        err('estructura', 'escenas', 'El guion no tiene escenas.')
        escenas = []
    elif len(escenas) > MAX_ESCENAS:
        err('estructura', 'escenas', f'Máximo {MAX_ESCENAS} escenas.')

    total = 0.0
    for i, e in enumerate(escenas, start=1):
        if not isinstance(e, dict):
            err('estructura', f'escena {i}', 'Formato inválido.')
            continue
        if not (e.get('texto_pantalla') or e.get('locucion')):
            err('estructura', f'escena {i}', 'Sin texto en pantalla ni locución.')
        if len(e.get('texto_pantalla') or '') > MAX_TEXTO_PANTALLA:
            err('estructura', f'escena {i}', f'Texto en pantalla de más de {MAX_TEXTO_PANTALLA} caracteres.')
        try:
            d = float(e.get('duracion_seg'))
        except (TypeError, ValueError):
            err('estructura', f'escena {i}', 'Duración inválida.')
            continue
        if not (1 <= d <= MAX_DURACION_ESCENA):
            err('estructura', f'escena {i}', f'Duración fuera de 1–{MAX_DURACION_ESCENA} segundos.')
        total += d
    if total > MAX_DURACION_TOTAL:
        err('estructura', 'escenas', f'Duración total de {total:.0f}s supera {MAX_DURACION_TOTAL}s.')

    if len(guion.get('caption') or '') > MAX_CAPTION:
        err('estructura', 'caption', f'El caption supera {MAX_CAPTION} caracteres.')
    n_hash = len((guion.get('hashtags') or '').split())
    if n_hash > MAX_HASHTAGS:
        err('estructura', 'hashtags', f'Más de {MAX_HASHTAGS} hashtags.')

    # ── Contenido ───────────────────────────────────────────────────────────
    corpus_norm = normalizar(corpus_fuente)
    corpus_compacto = re.sub(r'\s+', '', corpus_norm)
    permitidos = {_solo_digitos(c) for c in contactos_permitidos if _solo_digitos(c)}
    prohibidas = list(marca.lista_palabras_prohibidas)

    for campo, texto in _textos_publicos(guion):
        t = normalizar(texto)
        if not t.strip():
            continue

        for palabra in prohibidas:
            if re.search(patron_palabra_prohibida(palabra), t):
                err('palabra_prohibida', campo, f'Contiene la palabra prohibida "{palabra.rstrip("*")}".')

        if not marca.permite_precios:
            m = _PATRON_PRECIO.search(t) or ('$' in t and re.search(r'\$', t))
            if m:
                err('precio', campo, 'Menciona precios o costos y esta marca no lo permite.')

        if _PATRON_TESTIMONIO.search(t):
            err('testimonio', campo, 'Parece un testimonio o caso de paciente (no permitido).')

        for m in _PATRON_PORCENTAJE.finditer(t):
            if re.sub(r'\s+', '', m.group()) not in corpus_compacto:
                err('cifra_no_respaldada', campo, f'El porcentaje "{m.group().strip()}" no aparece en las fichas aprobadas.')

        for m in _PATRON_CANTIDAD_FUERTE.finditer(t):
            if m.group(1) not in corpus_norm:
                err('cifra_no_respaldada', campo,
                    f'La cifra "{m.group(1)} {m.group(2)}" no aparece en las fichas aprobadas.')

        for m in _PATRON_CANTIDAD_DEBIL.finditer(t):
            if m.group(1) not in corpus_norm:
                adv('cifra_dudosa', campo, f'"{m.group(1)} {m.group(2)}" no aparece en las fichas aprobadas.')

        for m in _PATRON_TELEFONO.finditer(texto or ''):
            digitos = _solo_digitos(m.group())
            if len(digitos) >= 7 and digitos not in permitidos and digitos not in re.sub(r'\D', '', corpus_fuente):
                err('telefono', campo, f'El número "{m.group().strip()}" no es un contacto registrado.')

    # ── Imágenes de niños generadas por IA ──────────────────────────────────
    if origen_visual != 'propias' and not permite_ninos_realistas:
        for i, e in enumerate(escenas, start=1):
            if not isinstance(e, dict):
                continue
            pv = normalizar(e.get('prompt_visual'))
            if _PATRON_NINO.search(pv) and _PATRON_REALISTA.search(pv):
                err('ninos_realistas', f'escena {i} (visual)',
                    'Pide niños fotorrealistas con IA. Usa estilo ilustración, 3D o personaje.')

    return {'valido': not errores, 'errores': errores, 'advertencias': advertencias}
