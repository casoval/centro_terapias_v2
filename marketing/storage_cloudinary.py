"""
Storage de Marketing sobre Cloudinary.

Reglas:
  - Todo se guarda bajo la carpeta `marketing/` (public_id con prefijo), para
    no mezclarse con las fotos de pacientes si se usa la cuenta principal.
  - Por defecto los archivos son de tipo `authenticated`: la URL lleva una
    firma y el archivo NO se puede adivinar ni listar. (Una URL firmada sí la
    puede abrir Instagram/Facebook cuando se automatice la publicación.)
  - Los credenciales se pasan en cada llamada; NO se toca `cloudinary.config()`
    global, que usan las fotos de pacientes.
  - Nombre guardado en BD = public_id (+ extensión en imagen/video). De ahí se
    deduce el tipo de recurso, así no hace falta un campo extra.
"""

import os
import uuid

import requests
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

EXT_IMAGEN = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tif', 'tiff', 'avif', 'heic'}
# Cloudinary guarda el audio dentro del tipo de recurso "video".
EXT_VIDEO = {'mp4', 'mov', 'webm', 'mkv', 'avi', 'm4v', 'mp3', 'wav', 'm4a', 'ogg', 'aac'}


def tipo_recurso(nombre):
    ext = os.path.splitext(nombre)[1].lstrip('.').lower()
    if ext in EXT_IMAGEN:
        return 'image'
    if ext in EXT_VIDEO:
        return 'video'
    return 'raw'


@deconstructible
class CloudinaryMarketingStorage(Storage):

    def __init__(self, cloud_name='', api_key='', api_secret='', carpeta='marketing', tipo='authenticated'):
        if not all([cloud_name, api_key, api_secret]):
            raise ImproperlyConfigured('Faltan credenciales de Cloudinary para Marketing.')
        self.cloud_name = cloud_name
        self.api_key = api_key
        self.api_secret = api_secret
        self.carpeta = carpeta.strip('/')
        self.tipo = tipo

    # ── utilidades ──────────────────────────────────────────────────────────
    @property
    def _cred(self):
        return {'cloud_name': self.cloud_name, 'api_key': self.api_key, 'api_secret': self.api_secret}

    def _partes(self, nombre):
        """(public_id, formato, tipo_recurso) a partir del nombre guardado."""
        rt = tipo_recurso(nombre)
        if rt == 'raw':
            return nombre, None, rt
        base, ext = os.path.splitext(nombre)
        return base, ext.lstrip('.').lower(), rt

    # ── API de Storage ──────────────────────────────────────────────────────
    def _save(self, name, content):
        import cloudinary.uploader

        directorio, archivo = os.path.split(name.replace('\\', '/'))
        archivo = self.get_valid_name(archivo)
        base, ext = os.path.splitext(archivo)
        rt = tipo_recurso(archivo)
        # Sufijo aleatorio: nunca se sobrescribe y no hace falta consultar `exists`.
        stem = f'{base}_{uuid.uuid4().hex[:8]}'
        partes = [p for p in (self.carpeta, directorio.strip('/')) if p]
        public_id = '/'.join(partes + [stem + (ext if rt == 'raw' else '')])

        if hasattr(content, 'seek'):
            content.seek(0)
        try:
            res = cloudinary.uploader.upload(
                content, public_id=public_id, resource_type=rt, type=self.tipo,
                overwrite=False, **self._cred,
            )
        except Exception as e:
            raise OSError(f'Cloudinary no aceptó el archivo de Marketing: {e}')

        if rt == 'raw':
            return res['public_id']
        formato = res.get('format') or ext.lstrip('.')
        return f"{res['public_id']}.{formato}"

    def url(self, name):
        import cloudinary.utils

        public_id, formato, rt = self._partes(name)
        opciones = {'resource_type': rt, 'type': self.tipo, 'secure': True,
                    'sign_url': self.tipo != 'upload', **self._cred}
        if formato:
            opciones['format'] = formato
        url, _ = cloudinary.utils.cloudinary_url(public_id, **opciones)
        return url

    def delete(self, name):
        import cloudinary.uploader

        public_id, _, rt = self._partes(name)
        try:
            cloudinary.uploader.destroy(
                public_id, resource_type=rt, type=self.tipo, invalidate=True, **self._cred,
            )
        except Exception as e:
            raise OSError(f'No se pudo borrar {name} de Cloudinary: {e}')

    def exists(self, name):
        # El nombre siempre lleva un sufijo aleatorio: nunca hay colisión.
        return False

    def size(self, name):
        import cloudinary.api

        public_id, _, rt = self._partes(name)
        try:
            return cloudinary.api.resource(public_id, resource_type=rt, type=self.tipo, **self._cred)['bytes']
        except Exception:
            return 0

    def _open(self, name, mode='rb'):
        r = requests.get(self.url(name), timeout=60)
        r.raise_for_status()
        return ContentFile(r.content, name=name)

    def listdir(self, path):
        raise NotImplementedError('Cloudinary no se lista como carpeta desde Django.')
