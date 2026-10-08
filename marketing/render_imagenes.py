"""
marketing/render_imagenes.py

Dibuja imágenes y diapositivas de carrusel con Pillow (sin IA, costo cero).

Módulo PURO: no toca la base de datos ni el storage. Recibe la marca (cualquier
objeto con sus atributos), el texto y, opcionalmente, una foto y un logo ya
cargados como imágenes PIL, y devuelve una imagen PIL. Por eso se puede probar
sin base de datos.

Roles de diapositiva:
  portada    gancho grande sobre foto (o degradado de la marca)
  contenido  texto en una tarjeta clara, legible sobre cualquier fondo
  cierre     fondo de marca con la llamada a la acción y los datos de contacto

Zonas seguras: en formato 9:16 (Reels, TikTok, Historias) las apps tapan la
parte de arriba y, sobre todo, la de abajo con botones y descripción; el texto
se mantiene fuera de esas franjas.
"""

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

RUTA_FUENTES = Path(__file__).resolve().parent / 'assets' / 'fonts'
FUENTE_NEGRITA = 'Poppins-Bold.ttf'
FUENTE_MEDIA = 'Poppins-Medium.ttf'
FUENTE_NORMAL = 'Poppins-Regular.ttf'

COLOR_PRIMARIO = '#1E3A8A'
COLOR_SECUNDARIO = '#0EA5E9'
COLOR_ACENTO = '#F59E0B'
TINTA = (15, 23, 42)
BLANCO = (255, 255, 255)

ROLES = ('portada', 'contenido', 'cierre')


# ── Color ───────────────────────────────────────────────────────────────────

def hex_a_rgb(valor, defecto):
    for candidato in (valor, defecto):
        v = (candidato or '').strip().lstrip('#')
        if len(v) == 6:
            try:
                return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                continue
    return (0, 0, 0)


def luminancia(rgb):
    def canal(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a, b):
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def color_texto_sobre(fondo):
    """Blanco o tinta oscura, el que mejor se lea sobre `fondo`."""
    return BLANCO if contraste(BLANCO, fondo) >= contraste(TINTA, fondo) else TINTA


def _colores(marca):
    return (
        hex_a_rgb(getattr(marca, 'color_primario', ''), COLOR_PRIMARIO),
        hex_a_rgb(getattr(marca, 'color_secundario', ''), COLOR_SECUNDARIO),
        hex_a_rgb(getattr(marca, 'color_acento', ''), COLOR_ACENTO),
    )


# ── Tipografía ──────────────────────────────────────────────────────────────

def fuente(nombre, tamano):
    try:
        return ImageFont.truetype(str(RUTA_FUENTES / nombre), int(tamano))
    except OSError:  # archivo ausente: que no se caiga el render
        return ImageFont.load_default(size=int(tamano))


def _partir_palabra(draw, palabra, fnt, ancho):
    trozos, actual = [], ''
    for ch in palabra:
        if draw.textlength(actual + ch, font=fnt) <= ancho:
            actual += ch
        else:
            trozos.append(actual)
            actual = ch
    trozos.append(actual)
    return trozos


def envolver(draw, texto, fnt, ancho):
    """Parte el texto en líneas que caben en `ancho` (respeta saltos de línea)."""
    lineas = []
    for parrafo in str(texto or '').splitlines() or ['']:
        actual = ''
        for palabra in parrafo.split():
            if draw.textlength(palabra, font=fnt) > ancho:  # palabra más ancha que la caja
                if actual:
                    lineas.append(actual)
                    actual = ''
                *previos, ultimo = _partir_palabra(draw, palabra, fnt, ancho)
                lineas.extend(previos)
                actual = ultimo
                continue
            prueba = f'{actual} {palabra}'.strip()
            if draw.textlength(prueba, font=fnt) <= ancho:
                actual = prueba
            else:
                lineas.append(actual)
                actual = palabra
        lineas.append(actual)
    return lineas


def ajustar_texto(draw, texto, archivo_fuente, ancho, alto, tam_max, tam_min, interlineado=1.18):
    """Busca el tamaño más grande (entre tam_max y tam_min) con el que el texto cabe."""
    tam = int(tam_max)
    while True:
        fnt = fuente(archivo_fuente, tam)
        lineas = envolver(draw, texto, fnt, ancho)
        paso = int(tam * interlineado)
        total = paso * len(lineas)
        if total <= alto or tam <= tam_min:
            if total > alto:  # ni al tamaño mínimo cabe: se recorta con puntos suspensivos
                maximo = max(1, int(alto // paso))
                lineas = lineas[:maximo]
                lineas[-1] = lineas[-1].rstrip(' .,;') + '…'
                total = paso * len(lineas)
            return fnt, lineas, paso, total
        tam = max(int(tam_min), int(tam * 0.94))


# ── Imágenes ────────────────────────────────────────────────────────────────

def abrir_imagen(origen, lado_max=2400):
    """Abre una imagen (ruta o archivo) corrigiendo la orientación de las fotos de celular."""
    img = Image.open(origen)
    img = ImageOps.exif_transpose(img)
    img.thumbnail((lado_max, lado_max))
    return img.convert('RGBA')


def cubrir(img, ancho, alto):
    """Recorta y escala la imagen para llenar ancho x alto sin deformarla."""
    return ImageOps.fit(img.convert('RGB'), (ancho, alto), method=Image.LANCZOS, centering=(0.5, 0.45))


def _degradado(ancho, alto, c1, c2):
    mascara = Image.linear_gradient('L').resize((ancho, alto))
    return Image.composite(Image.new('RGB', (ancho, alto), c2), Image.new('RGB', (ancho, alto), c1), mascara)


def _oscurecer(base, minimo, maximo):
    """Velo negro más fuerte abajo, para que el texto se lea sobre cualquier foto."""
    gradiente = Image.linear_gradient('L').resize(base.size)
    alfa = gradiente.point(lambda v: int(minimo + (maximo - minimo) * v / 255))
    velo = Image.new('RGB', base.size, (0, 0, 0))
    base.paste(velo, (0, 0), alfa)


def _decoracion(base, acento, ancho, alto):
    """Círculos suaves con el color de acento: da identidad cuando no hay foto."""
    capa = Image.new('RGBA', base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    r = int(ancho * 0.55)
    d.ellipse((ancho - r * 0.6, -r * 0.5, ancho + r * 0.4, r * 0.5 + 0), fill=(*acento, 46))
    r2 = int(ancho * 0.42)
    d.ellipse((-r2 * 0.5, alto - r2 * 0.7, r2 * 0.7, alto + r2 * 0.3), fill=(*acento, 38))
    base.alpha_composite(capa)


def _texto_sombreado(base, items, ancho_px, color=BLANCO):
    """Dibuja texto blanco con una sombra suave. items = [((x, y), texto, fuente), ...]"""
    capa = Image.new('RGBA', base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    desplazo = max(2, ancho_px // 300)
    for (x, y), texto, fnt in items:
        d.text((x + desplazo, y + desplazo), texto, font=fnt, fill=(0, 0, 0, 190))
    capa = capa.filter(ImageFilter.GaussianBlur(max(3, ancho_px // 140)))
    base.alpha_composite(capa)
    d = ImageDraw.Draw(base)
    for (x, y), texto, fnt in items:
        d.text((x, y), texto, font=fnt, fill=color)


# ── Márgenes ────────────────────────────────────────────────────────────────

def _margenes(ancho, alto):
    mx = int(ancho * 0.08)
    if alto / ancho >= 1.7:  # 9:16
        return mx, int(alto * 0.13), int(alto * 0.20)
    return mx, int(alto * 0.07), int(alto * 0.10)


# ── Elementos de marca ──────────────────────────────────────────────────────

def _pegar_logo_o_nombre(base, marca, logo, ancho, alto, mx, y):
    d = ImageDraw.Draw(base)
    pad = int(ancho * 0.022)
    if logo is not None:
        max_w, max_h = int(ancho * 0.30), int(alto * 0.075)
        lg = logo.copy()
        lg.thumbnail((max_w, max_h))
        caja = (mx, y, mx + lg.width + pad * 2, y + lg.height + pad * 2)
        d.rounded_rectangle(caja, radius=pad * 1.4, fill=(255, 255, 255, 235))
        base.alpha_composite(lg, (mx + pad, y + pad))
    else:
        nombre = (getattr(marca, 'nombre', '') or '').upper()
        if not nombre:
            return
        fnt = fuente(FUENTE_NEGRITA, int(ancho * 0.032))
        w = d.textlength(nombre, font=fnt)
        caja = (mx, y, mx + w + pad * 2, y + int(ancho * 0.032 * 1.3) + pad * 2)
        d.rounded_rectangle(caja, radius=pad * 1.4, fill=(255, 255, 255, 235))
        d.text((mx + pad, y + pad), nombre, font=fnt, fill=TINTA)


def _puntos(base, indice, total, acento, ancho, alto, y):
    if total <= 1:
        return
    d = ImageDraw.Draw(base)
    r = max(5, int(ancho * 0.008))
    sep = r * 4
    ancho_total = sep * (total - 1)
    x0 = (ancho - ancho_total) // 2
    for i in range(total):
        cx = x0 + i * sep
        color = (*acento, 255) if i + 1 == indice else (255, 255, 255, 140)
        d.ellipse((cx - r, y - r, cx + r, y + r), fill=color)


def _lineas_contacto(marca):
    lineas = []
    if getattr(marca, 'whatsapp', ''):
        lineas.append(f'WhatsApp: {marca.whatsapp}')
    if getattr(marca, 'url_web', ''):
        lineas.append(marca.url_web.replace('https://', '').replace('http://', '').rstrip('/'))
    for campo in ('cuenta_instagram', 'cuenta_facebook', 'cuenta_tiktok'):
        valor = (getattr(marca, campo, '') or '').strip()
        if valor:
            lineas.append(valor if valor.startswith('@') or '/' in valor else f'@{valor}')
            break
    return lineas


# ── Diapositivas ────────────────────────────────────────────────────────────

def _portada(base, texto, marca, ancho, alto, mx, sup, inf, acento, indice, total):
    d = ImageDraw.Draw(base)
    caja_w, caja_h = ancho - 2 * mx, int(alto * 0.46)
    fnt, lineas, paso, total_h = ajustar_texto(
        d, texto, FUENTE_NEGRITA, caja_w, caja_h, ancho * 0.105, ancho * 0.05,
    )
    y0 = int(alto * 0.5 - total_h / 2) if alto / ancho < 1.7 else int(alto * 0.45 - total_h / 2)
    barra_h = max(8, int(ancho * 0.012))
    d.rounded_rectangle((mx, y0 - barra_h * 3, mx + int(ancho * 0.18), y0 - barra_h * 2),
                        radius=barra_h, fill=(*acento, 255))
    items = [((mx, y0 + i * paso), linea, fnt) for i, linea in enumerate(lineas)]
    if total > 1:
        pie = fuente(FUENTE_MEDIA, int(ancho * 0.034))
        txt = 'Desliza »'
        w = d.textlength(txt, font=pie)
        items.append(((ancho - mx - w, alto - inf - int(ancho * 0.05)), txt, pie))
    _texto_sombreado(base, items, ancho)


def _contenido(base, texto, marca, ancho, alto, mx, sup, inf, primario, acento):
    d = ImageDraw.Draw(base)
    pad = int(ancho * 0.06)
    caja_w = ancho - 2 * mx
    util_h = alto - sup - inf
    fnt, lineas, paso, total_h = ajustar_texto(
        d, texto, FUENTE_NEGRITA, caja_w - 2 * pad - int(ancho * 0.03), int(util_h * 0.62) - 2 * pad,
        ancho * 0.080, ancho * 0.040,
    )
    tarjeta_h = total_h + 2 * pad
    # Tarjeta centrada en la zona segura, algo hacia abajo si hay foto detrás.
    y1 = sup + int((util_h - tarjeta_h) * 0.62)
    tarjeta = (mx, y1, mx + caja_w, y1 + tarjeta_h)
    sombra = Image.new('RGBA', base.size, (0, 0, 0, 0))
    ImageDraw.Draw(sombra).rounded_rectangle(
        (tarjeta[0], tarjeta[1] + int(ancho * 0.012), tarjeta[2], tarjeta[3] + int(ancho * 0.012)),
        radius=int(ancho * 0.04), fill=(0, 0, 0, 70))
    base.alpha_composite(sombra)
    d = ImageDraw.Draw(base)
    d.rounded_rectangle(tarjeta, radius=int(ancho * 0.04), fill=(255, 255, 255, 244))
    bw = max(10, int(ancho * 0.014))
    d.rounded_rectangle((tarjeta[0] + pad // 2, tarjeta[1] + pad, tarjeta[0] + pad // 2 + bw, tarjeta[3] - pad),
                        radius=bw // 2, fill=(*acento, 255))
    color = primario if contraste(primario, BLANCO) >= 4.5 else TINTA
    x = tarjeta[0] + pad // 2 + bw + int(ancho * 0.03)
    for i, linea in enumerate(lineas):
        d.text((x, tarjeta[1] + pad + i * paso), linea, font=fnt, fill=color)


def _cierre(base, texto, marca, ancho, alto, mx, sup, inf, primario, acento):
    d = ImageDraw.Draw(base)
    color = color_texto_sobre(primario)
    contacto = _lineas_contacto(marca)
    fc = fuente(FUENTE_MEDIA, int(ancho * 0.040))
    paso_c = int(ancho * 0.040 * 1.5)
    alto_contacto = paso_c * len(contacto)
    util_h = alto - sup - inf
    caja_w = ancho - 2 * mx
    fnt, lineas, paso, total_h = ajustar_texto(
        d, texto, FUENTE_NEGRITA, caja_w, int(util_h * 0.55), ancho * 0.090, ancho * 0.044,
    )
    bloque = total_h + (int(ancho * 0.05) + alto_contacto if contacto else 0)
    y0 = sup + int((util_h - bloque) / 2)
    for i, linea in enumerate(lineas):
        d.text((mx, y0 + i * paso), linea, font=fnt, fill=color)
    y = y0 + total_h + int(ancho * 0.03)
    if contacto:
        d.rounded_rectangle((mx, y, mx + int(ancho * 0.18), y + max(8, int(ancho * 0.012))),
                            radius=6, fill=(*acento, 255))
        y += int(ancho * 0.03)
        for linea in contacto:
            d.text((mx, y), linea, font=fc, fill=color)
            y += paso_c


def renderizar(marca, rol, texto, *, ancho, alto, indice=1, total=1, foto=None, logo=None):
    """
    Devuelve una imagen PIL (RGB) de ancho x alto.

    marca  objeto con nombre, colores (#RRGGBB), whatsapp, url_web, cuentas…
    rol    'portada' | 'contenido' | 'cierre'
    foto   PIL.Image opcional como fondo (portada y contenido)
    logo   PIL.Image opcional (se muestra arriba a la izquierda)
    """
    if rol not in ROLES:
        raise ValueError(f'Rol inválido: {rol}')
    primario, secundario, acento = _colores(marca)
    mx, sup, inf = _margenes(ancho, alto)

    if rol == 'cierre':
        base = _degradado(ancho, alto, primario, secundario).convert('RGBA')
        _decoracion(base, acento, ancho, alto)
    elif foto is not None:
        base = cubrir(foto, ancho, alto)
        _oscurecer(base, 70 if rol == 'portada' else 40, 190 if rol == 'portada' else 120)
        base = base.convert('RGBA')
    else:
        base = _degradado(ancho, alto, primario, secundario).convert('RGBA')
        _decoracion(base, acento, ancho, alto)
        if rol == 'portada':
            _oscurecer_rgba = base.convert('RGB')
            _oscurecer(_oscurecer_rgba, 20, 90)
            base = _oscurecer_rgba.convert('RGBA')

    _pegar_logo_o_nombre(base, marca, logo, ancho, alto, mx, int(sup * 0.45) if alto / ancho >= 1.7 else int(alto * 0.04))

    if rol == 'portada':
        _portada(base, texto, marca, ancho, alto, mx, sup, inf, acento, indice, total)
    elif rol == 'contenido':
        _contenido(base, texto, marca, ancho, alto, mx, sup, inf, primario, acento)
    else:
        _cierre(base, texto, marca, ancho, alto, mx, sup, inf, primario, acento)

    _puntos(base, indice, total, acento, ancho, alto, alto - int(inf * 0.45))
    return base.convert('RGB')


def a_jpeg(img, calidad=92):
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=calidad, optimize=True, progressive=True)
    return buf.getvalue()


def miniatura(img, ancho=480):
    t = img.copy()
    t.thumbnail((ancho, ancho * 2))
    return t
