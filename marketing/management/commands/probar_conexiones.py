"""
Prueba real de las conexiones de Marketing: Gemini y el almacenamiento.

    python manage.py probar_conexiones
    python manage.py probar_conexiones --solo gemini
    python manage.py probar_conexiones --solo almacenamiento

Gemini: una llamada mínima (unos pocos tokens).
Almacenamiento: sube un PNG de 1 píxel, pide su URL y lo borra.
"""

import base64

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from marketing.proveedores.base import ProveedorError, extraer_json
from marketing.proveedores.registro import listar_proveedores_texto, obtener_proveedor_texto
from marketing.storage_backends import get_marketing_storage

PNG_1PX = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)


class Command(BaseCommand):
    help = 'Prueba Gemini y el almacenamiento de Marketing (sube y borra un archivo de prueba).'

    def add_arguments(self, parser):
        parser.add_argument('--solo', choices=['gemini', 'almacenamiento'])

    def handle(self, *args, **opts):
        fallos = 0
        if opts['solo'] in (None, 'gemini'):
            fallos += not self._gemini()
        if opts['solo'] in (None, 'almacenamiento'):
            fallos += not self._almacenamiento()
        if fallos:
            raise SystemExit(1)

    def _ok(self, msg):
        self.stdout.write(self.style.SUCCESS(f'  OK  {msg}'))
        return True

    def _mal(self, msg):
        self.stdout.write(self.style.ERROR(f'  ERROR  {msg}'))
        return False

    def _gemini(self):
        self.stdout.write('Gemini')
        estado = {p['id']: p for p in listar_proveedores_texto()}
        if not estado['gemini']['disponible']:
            return self._mal('Falta GEMINI_API_KEY en el .env.')
        try:
            r = obtener_proveedor_texto('gemini').generar(
                'Responde SOLO con JSON válido.', 'Devuelve {"ok": true}', temperatura=0,
            )
            extraer_json(r.texto)
        except ProveedorError as e:
            return self._mal(str(e))
        return self._ok(f'modelo {r.modelo} respondió ({r.tokens_entrada} tokens de entrada).')

    def _almacenamiento(self):
        self.stdout.write('Almacenamiento')
        storage = get_marketing_storage()
        tipo = type(storage).__name__
        if getattr(settings, 'IS_PRODUCTION', False) and tipo == 'MarketingNoConfiguradoStorage':
            return self._mal('Producción sin almacenamiento configurado (ver config/settings.py).')
        try:
            nombre = storage.save('pruebas/conexion.png', ContentFile(PNG_1PX))
            url = storage.url(nombre)
            self._ok(f'{tipo}: guardó {nombre}')
            self.stdout.write(f'      URL: {url}')
            storage.delete(nombre)
            return self._ok('borró el archivo de prueba.')
        except Exception as e:
            return self._mal(f'{tipo}: {e}')
