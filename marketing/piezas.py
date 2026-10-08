"""
marketing/piezas.py

Piezas gráficas (imagen única o carrusel) hechas con plantillas de la marca
(Pillow, sin IA y sin costo). Flujo:

    guion APROBADO -> crear_pieza -> generar_pieza -> (editar textos) -> aprobar_pieza
                   -> preparar_publicacion -> marcar como publicada (a mano)

Reglas:
  - Solo se parte de un guion aprobado.
  - Las fotos de fondo salen únicamente de los Activos de la campaña que sean
    `usable_en_publicidad` (consentimiento). Se vuelve a comprobar al generar
    y al aprobar.
  - Todo texto editado por el dueño pasa por el MISMO validador de contenido
    que los guiones (palabras prohibidas, precios, testimonios, cifras…).
"""

import io
import zipfile

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from . import render_imagenes as ri
from .guiones import GuionError, _validar, construir_contexto
from .models import AuditoriaMarketing, DIMENSIONES_FORMATO, Elemento, Pieza, Publicacion

MAX_DIAPOSITIVAS = 10
FORMATOS_PERMITIDOS = ('4x5', '1x1', '9x16')
TIPOS_PERMITIDOS = ('imagen', 'carrusel')
MAX_TEXTO = 300  # Elemento.texto_pantalla


class PiezaError(Exception):
    """Error de uso (guion sin aprobar, textos inválidos, estado incorrecto…)."""


def _auditar(usuario, accion, objeto, detalle=None):
    AuditoriaMarketing.objects.create(
        usuario=usuario, accion=accion, objeto_tipo=type(objeto).__name__,
        objeto_id=str(objeto.pk), detalle=detalle or {},
    )


# ── Creación ────────────────────────────────────────────────────────────────

def _fotos_usables(campana):
    """(activos usables, cantidad excluida por falta de autorización)."""
    if campana.origen_visual == 'ia_total':
        return [], 0
    todos = [a for a in campana.activos_referencia.filter(tipo='imagen') if a.activo]
    usables = [a for a in todos if a.usable_en_publicidad]
    return usables, len(todos) - len(usables)


def _plan_diapositivas(guion, tipo, marca):
    """Lista de (rol, texto, indice_escena|None, locucion, prompt_visual)."""
    cierre = marca.cierre_fijo.strip() or 'Escríbenos por WhatsApp'
    plan = [('portada', guion.gancho, None, '', '')]
    if tipo == 'carrusel':
        for i, e in enumerate(guion.escenas or []):
            texto = (e.get('texto_pantalla') or '').strip()
            if texto:
                plan.append(('contenido', texto, i, e.get('locucion', ''), e.get('prompt_visual', '')))
        plan.append(('cierre', cierre, None, '', ''))
    return plan


@transaction.atomic
def crear_pieza(campana, guion, tipo, formato, usuario=None):
    """Crea la pieza y sus diapositivas (aún sin imágenes). Devuelve (pieza, avisos)."""
    if guion.campana_id != campana.pk:
        raise PiezaError('Ese guion no pertenece a esta campaña.')
    if guion.estado != 'aprobado':
        raise PiezaError('Solo se pueden crear piezas a partir de un guion APROBADO.')
    if tipo not in TIPOS_PERMITIDOS:
        raise PiezaError('Por ahora se pueden crear imágenes y carruseles. El video llega después.')
    if formato not in FORMATOS_PERMITIDOS:
        raise PiezaError('Formato no disponible para imágenes. Usa 4:5, 1:1 o 9:16.')

    plan = _plan_diapositivas(guion, tipo, campana.marca)
    if len(plan) > MAX_DIAPOSITIVAS:
        raise PiezaError(
            f'El carrusel tendría {len(plan)} diapositivas y el máximo es {MAX_DIAPOSITIVAS}. '
            'Acorta el guion (menos escenas) y vuelve a aprobarlo.'
        )
    if tipo == 'carrusel' and len(plan) < 3:
        raise PiezaError('Un carrusel necesita al menos una escena con texto en pantalla.')
    if any(len(p[1]) > MAX_TEXTO for p in plan):
        raise PiezaError(f'Algún texto supera {MAX_TEXTO} caracteres.')

    fotos, excluidas = _fotos_usables(campana)
    avisos = []
    if excluidas:
        avisos.append(
            f'{excluidas} foto(s) de la campaña no se usaron porque no tienen autorización confirmada '
            'para publicidad (ver Activos).'
        )
    if campana.origen_visual != 'ia_total' and not fotos:
        avisos.append('No hay fotos autorizadas en la campaña: se usó el fondo de color de la marca.')

    pieza = Pieza.objects.create(
        campana=campana, guion=guion, tipo=tipo, formato=formato, modo='plantilla',
        calidad='final', estado='pendiente', creada_por=usuario,
        datos_trabajo={'roles': [p[0] for p in plan], 'escenas': [p[2] for p in plan]},
    )
    n_foto = 0
    for orden, (rol, texto, _idx, locucion, visual) in enumerate(plan, start=1):
        activo = None
        if rol != 'cierre' and fotos:
            activo = fotos[n_foto % len(fotos)]
            n_foto += 1
        Elemento.objects.create(
            pieza=pieza, orden=orden, tipo='diapositiva', texto_pantalla=texto,
            locucion=locucion, prompt_visual=visual, activo_referencia=activo,
        )
    _auditar(usuario, 'pieza_creada', pieza, {'tipo': tipo, 'formato': formato, 'diapositivas': len(plan)})
    return pieza, avisos


# ── Generación ──────────────────────────────────────────────────────────────

def _rol(pieza, elemento):
    roles = (pieza.datos_trabajo or {}).get('roles') or []
    if 0 < elemento.orden <= len(roles):
        return roles[elemento.orden - 1]
    return 'portada' if elemento.orden == 1 else 'contenido'


def _cargar_logo(marca):
    if not marca.logo:
        return None
    try:
        with marca.logo.open('rb') as f:
            return ri.abrir_imagen(io.BytesIO(f.read()), lado_max=800)
    except Exception:
        return None  # sin logo se muestra el nombre de la marca


def _borrar_archivo(campo):
    try:
        if campo:
            campo.delete(save=False)
    except Exception:
        pass  # un archivo huérfano no debe impedir regenerar


def _renderizar_elemento(pieza, elemento, logo, cache_fotos):
    ancho, alto = pieza.dimensiones
    foto = None
    activo = elemento.activo_referencia
    if activo is not None:
        if not activo.usable_en_publicidad:
            raise PiezaError(f'La foto "{activo.nombre}" ya no tiene autorización vigente para publicidad.')
        if activo.pk not in cache_fotos:
            with activo.archivo.open('rb') as f:
                cache_fotos[activo.pk] = ri.abrir_imagen(io.BytesIO(f.read()))
        foto = cache_fotos[activo.pk]
    total = pieza.elementos.count()
    return ri.renderizar(
        pieza.campana.marca, _rol(pieza, elemento), elemento.texto_pantalla,
        ancho=ancho, alto=alto, indice=elemento.orden, total=total, foto=foto, logo=logo,
    )


def generar_pieza(pieza, solo_ids=None):
    """
    Dibuja las diapositivas y las guarda en el almacenamiento de Marketing.
    `solo_ids`: ids de Elemento a redibujar (por defecto, todos).
    Nunca lanza: si algo falla deja la pieza en 'fallida' con el motivo.
    """
    pieza.estado = 'generando'
    pieza.error = ''
    pieza.intentos += 1
    pieza.save(update_fields=['estado', 'error', 'intentos', 'actualizada'])
    try:
        logo = _cargar_logo(pieza.campana.marca)
        cache_fotos = {}
        elementos = list(pieza.elementos.select_related('activo_referencia').order_by('orden'))
        primera = None
        for el in elementos:
            if solo_ids is not None and el.pk not in solo_ids and el.archivo:
                continue
            img = _renderizar_elemento(pieza, el, logo, cache_fotos)
            _borrar_archivo(el.archivo)
            el.archivo.save(f'pieza{pieza.pk}_{el.orden:02d}.jpg', ContentFile(ri.a_jpeg(img)), save=False)
            el.estado, el.error = 'listo', ''
            el.save(update_fields=['archivo', 'estado', 'error'])
            if el.orden == 1:
                primera = img
        if primera is not None:
            _borrar_archivo(pieza.miniatura)
            pieza.miniatura.save(
                f'pieza{pieza.pk}_mini.jpg', ContentFile(ri.a_jpeg(ri.miniatura(primera), 82)), save=False,
            )
        if pieza.tipo == 'imagen':
            primero = elementos[0]
            pieza.archivo_final = primero.archivo.name
        pieza.estado = 'listo'
        pieza.aprobada_por, pieza.aprobada_en = None, None
    except Exception as e:
        pieza.estado = 'fallida'
        pieza.error = str(e)[:1000]
    pieza.save()
    return pieza


# ── Edición de textos ───────────────────────────────────────────────────────

def validar_textos(pieza, textos):
    """
    Revalida con las reglas de la marca los textos editados. `textos`: {id_elemento: texto}.
    Devuelve el resultado del validador (valido, errores, advertencias).
    """
    guion = pieza.guion
    contexto = construir_contexto(pieza.campana)
    escenas = [dict(e) for e in (guion.escenas or [])]
    gancho = guion.gancho
    cierre = ''
    roles = (pieza.datos_trabajo or {}).get('roles') or []
    mapa = (pieza.datos_trabajo or {}).get('escenas') or []
    for el in pieza.elementos.all():
        texto = textos.get(el.pk, el.texto_pantalla)
        rol = roles[el.orden - 1] if el.orden <= len(roles) else 'contenido'
        if rol == 'portada':
            gancho = texto
        elif rol == 'cierre':
            cierre = texto
        else:
            idx = mapa[el.orden - 1] if el.orden <= len(mapa) else None
            if idx is not None and idx < len(escenas):
                escenas[idx]['texto_pantalla'] = texto
    return _validar(pieza.campana, contexto, {
        'gancho': gancho, 'escenas': escenas,
        'caption': f'{guion.caption}\n{cierre}'.strip(), 'hashtags': guion.hashtags,
    })


def actualizar_textos(pieza, textos, usuario=None):
    """
    Guarda textos editados (dict {id_elemento: texto}), valida y redibuja solo
    las diapositivas que cambiaron. Una pieza aprobada vuelve a 'listo'.
    """
    if pieza.estado in ('generando', 'cancelada', 'publicada'):
        raise PiezaError('La pieza no se puede editar en este estado.')
    cambios = {}
    for el in pieza.elementos.all():
        if el.pk in textos:
            nuevo = ' '.join(str(textos[el.pk]).split())
            if not nuevo:
                raise PiezaError(f'La diapositiva {el.orden} no puede quedar sin texto.')
            if len(nuevo) > MAX_TEXTO:
                raise PiezaError(f'La diapositiva {el.orden} supera {MAX_TEXTO} caracteres.')
            if nuevo != el.texto_pantalla:
                cambios[el.pk] = nuevo
    if not cambios:
        return pieza, 0
    validacion = validar_textos(pieza, cambios)
    if not validacion['valido']:
        detalle = '; '.join(f'{e["campo"]}: {e["detalle"]}' for e in validacion['errores'][:4])
        raise PiezaError(f'El texto no cumple las reglas de la marca. {detalle}')
    for el in pieza.elementos.filter(pk__in=cambios):
        el.texto_pantalla = cambios[el.pk]
        el.save(update_fields=['texto_pantalla'])
    _auditar(usuario, 'pieza_texto_editado', pieza, {'diapositivas': sorted(cambios)})
    generar_pieza(pieza, solo_ids=set(cambios))
    return pieza, len(cambios)


# ── Aprobación ──────────────────────────────────────────────────────────────

def aprobar_pieza(pieza, usuario):
    if pieza.estado not in ('listo', 'aprobado'):
        raise PiezaError('Solo se puede aprobar una pieza que esté lista para revisar.')
    if pieza.guion is None or pieza.guion.estado != 'aprobado':
        raise PiezaError('El guion de esta pieza ya no está aprobado.')
    elementos = list(pieza.elementos.select_related('activo_referencia'))
    if not elementos or any(e.estado != 'listo' or not e.archivo for e in elementos):
        raise PiezaError('Hay diapositivas sin generar.')
    for e in elementos:
        if e.activo_referencia is not None and not e.activo_referencia.usable_en_publicidad:
            raise PiezaError(
                f'La foto "{e.activo_referencia.nombre}" ya no tiene autorización vigente. '
                'Regenera la pieza sin esa foto.'
            )
    validacion = validar_textos(pieza, {})
    if not validacion['valido']:
        raise PiezaError('Los textos ya no cumplen las reglas actuales de la marca. Edítalos y vuelve a intentar.')
    pieza.estado = 'aprobado'
    pieza.aprobada_por = usuario
    pieza.aprobada_en = timezone.now()
    pieza.save(update_fields=['estado', 'aprobada_por', 'aprobada_en', 'actualizada'])
    _auditar(usuario, 'pieza_aprobada', pieza)
    return pieza


# ── Descarga ────────────────────────────────────────────────────────────────

def _bytes(campo):
    with campo.open('rb') as f:
        return f.read()


def paquete_descarga(pieza):
    """(nombre, contenido, tipo_mime): el JPG si es una imagen, un ZIP si es un carrusel."""
    elementos = list(pieza.elementos.order_by('orden'))
    if any(not e.archivo for e in elementos):
        raise PiezaError('La pieza aún no tiene todas sus imágenes.')
    base = f'pieza{pieza.pk}'
    if pieza.tipo == 'imagen':
        return f'{base}.jpg', _bytes(elementos[0].archivo), 'image/jpeg'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:  # JPG ya está comprimido
        for e in elementos:
            z.writestr(f'{base}_{e.orden:02d}.jpg', _bytes(e.archivo))
        guion = pieza.guion
        if guion is not None:
            z.writestr(f'{base}_texto.txt', f'{guion.caption}\n\n{guion.hashtags}\n'.encode('utf-8'))
    return f'{base}.zip', buf.getvalue(), 'application/zip'


# ── Publicación (manual) ────────────────────────────────────────────────────

def preparar_publicacion(pieza, red, usuario=None):
    if pieza.estado not in ('aprobado', 'publicada'):
        raise PiezaError('Aprueba la pieza antes de preparar su publicación.')
    if red not in {r for r, _ in Publicacion._meta.get_field('red').choices}:
        raise PiezaError('Red social no válida.')
    existente = pieza.publicaciones.filter(red=red).exclude(estado='descartada').first()
    if existente:
        return existente, False
    guion = pieza.guion
    pub = Publicacion.objects.create(
        pieza=pieza, red=red, caption=guion.caption if guion else '',
        hashtags=guion.hashtags if guion else '', registrada_por=usuario,
    )
    _auditar(usuario, 'publicacion_preparada', pub, {'red': red})
    return pub, True


def validar_publicacion(pieza, caption, hashtags):
    contexto = construir_contexto(pieza.campana)
    guion = pieza.guion
    return _validar(pieza.campana, contexto, {
        'gancho': guion.gancho, 'escenas': guion.escenas, 'caption': caption, 'hashtags': hashtags,
    })


def actualizar_publicacion(pub, caption, hashtags, usuario=None):
    """Guarda el texto de la publicación solo si cumple las reglas de la marca."""
    if pub.estado != 'preparada':
        raise PiezaError('Solo se edita una publicación que está preparada.')
    validacion = validar_publicacion(pub.pieza, caption, hashtags)
    if not validacion['valido']:
        detalle = '; '.join(f'{e["campo"]}: {e["detalle"]}' for e in validacion['errores'][:4])
        raise PiezaError(f'El texto no cumple las reglas de la marca. {detalle}')
    pub.caption, pub.hashtags = caption.strip(), ' '.join(hashtags.split())
    pub.save(update_fields=['caption', 'hashtags'])
    _auditar(usuario, 'publicacion_editada', pub)
    return pub


def registrar_publicada(pub, usuario, url='', etiqueta_ia=False):
    if pub.estado != 'preparada':
        raise PiezaError('Esta publicación ya fue registrada o descartada.')
    pub.etiqueta_ia_activada = bool(etiqueta_ia)
    pub.marcar_publicada(usuario, url=url)
    pub.save(update_fields=['etiqueta_ia_activada'])
    pieza = pub.pieza
    if pieza.estado != 'publicada':
        pieza.estado = 'publicada'
        pieza.save(update_fields=['estado', 'actualizada'])
    _auditar(usuario, 'publicacion_registrada', pub, {'red': pub.red, 'url': url})
    return pub


def descartar_publicacion(pub, usuario=None):
    if pub.estado != 'preparada':
        raise PiezaError('Solo se descarta una publicación que está preparada.')
    pub.estado = 'descartada'
    pub.save(update_fields=['estado'])
    _auditar(usuario, 'publicacion_descartada', pub)
    return pub


def eliminar_pieza(pieza, usuario=None):
    if pieza.publicaciones.filter(estado='publicada').exists():
        raise PiezaError('Esta pieza tiene publicaciones registradas y no se puede eliminar.')
    for el in pieza.elementos.all():
        _borrar_archivo(el.archivo)
    _borrar_archivo(pieza.miniatura)
    _auditar(usuario, 'pieza_eliminada', pieza, {'campana': pieza.campana_id})
    pieza.delete()
