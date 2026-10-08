"""
Sincroniza las fichas de contenido de Centro Misael desde las fuentes del
proyecto (páginas públicas de servicios y sedes).

Reglas (pensadas para no pisar el trabajo del dueño):
  - Una ficha NUEVA se crea SIN aprobar: el dueño la revisa y la aprueba.
  - Si la fuente cambió y la ficha no fue editada a mano -> se actualiza y
    se QUITA la aprobación (hay que volver a aprobar el texto nuevo).
  - Si la ficha fue editada a mano -> se CONSERVA tal cual (no se pisa).
"""

import hashlib

from .fuentes import fichas_servicios_publicos, texto_ficha_sedes
from .models import FichaContenido, Marca

SLUG_MARCA_CENTRO = 'centro-misael'


def huella(texto):
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()


def _sincronizar_una(marca, fuente, clave, titulo, texto, tipo, resumen):
    h = huella(texto)
    ficha = FichaContenido.objects.filter(marca=marca, fuente=fuente, clave_fuente=clave).first()
    if ficha is None:
        FichaContenido.objects.create(
            marca=marca, tipo=tipo, titulo=titulo, texto=texto,
            fuente=fuente, clave_fuente=clave, huella_fuente=h, aprobada=False,
        )
        resumen['creadas'] += 1
        return
    if ficha.texto == texto:
        if ficha.huella_fuente != h:
            FichaContenido.objects.filter(pk=ficha.pk).update(huella_fuente=h)
        resumen['sin_cambios'] += 1
        return
    if huella(ficha.texto) != ficha.huella_fuente:
        resumen['conservadas_editadas'] += 1   # editada a mano: no se toca
        return
    ficha.titulo = titulo
    ficha.texto = texto
    ficha.huella_fuente = h
    ficha.aprobada = False
    ficha.aprobada_por = None
    ficha.aprobada_en = None
    ficha.save()
    resumen['actualizadas'] += 1


def sincronizar_fichas_centro():
    """Devuelve un resumen {creadas, actualizadas, sin_cambios, conservadas_editadas}."""
    marca = Marca.objects.filter(slug=SLUG_MARCA_CENTRO).first()
    if marca is None:
        raise ValueError(
            f'No existe la marca "{SLUG_MARCA_CENTRO}". Ejecuta primero: '
            'python manage.py cargar_marcas_iniciales'
        )
    resumen = {'creadas': 0, 'actualizadas': 0, 'sin_cambios': 0, 'conservadas_editadas': 0}
    for f in fichas_servicios_publicos():
        _sincronizar_una(marca, 'servicios_data', f['clave'], f['titulo'], f['texto'], f['tipo'], resumen)
    sedes = texto_ficha_sedes()
    if sedes:
        _sincronizar_una(marca, 'sucursales', 'sedes', 'Sedes del centro', sedes, 'institucional', resumen)
    return resumen
