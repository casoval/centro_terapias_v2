from django.core.management.base import BaseCommand, CommandError

from marketing.guiones import GuionError, generar_guiones
from marketing.models import Campana
from marketing.proveedores.base import ProveedorError
from marketing.proveedores.registro import listar_proveedores_texto, obtener_proveedor_texto


class Command(BaseCommand):
    help = 'Genera guion(es) con IA para una campaña y muestra el resultado de la validación.'

    def add_arguments(self, parser):
        parser.add_argument('campana_id', type=int)
        parser.add_argument('--cantidad', type=int, default=1, help='1 a 3 variantes')
        parser.add_argument('--proveedor', default=None, help='gemini | groq')

    def handle(self, *args, **o):
        try:
            campana = Campana.objects.get(pk=o['campana_id'])
        except Campana.DoesNotExist:
            raise CommandError(f'No existe la campaña {o["campana_id"]}.')
        self.stdout.write('Proveedores: ' + ', '.join(
            f'{p["id"]}={"sí" if p["disponible"] else "sin clave"}' for p in listar_proveedores_texto()))
        try:
            proveedor = obtener_proveedor_texto(o['proveedor'])
            guiones = generar_guiones(campana, cantidad=o['cantidad'], proveedor=proveedor)
        except (GuionError, ProveedorError) as e:
            raise CommandError(str(e))
        for g in guiones:
            self.stdout.write(self.style.SUCCESS(f'\nGuion v{g.version} [{g.get_estado_display()}]') if g.estado == 'validado'
                              else self.style.WARNING(f'\nGuion v{g.version} [{g.get_estado_display()}]'))
            self.stdout.write(f'Gancho: {g.gancho}')
            for i, e in enumerate(g.escenas, 1):
                self.stdout.write(f'  {i}. ({e["duracion_seg"]}s) {e["texto_pantalla"]} | {e["locucion"]}')
            self.stdout.write(f'Caption: {g.caption}\nHashtags: {g.hashtags}')
            for e in g.validacion.get('errores', []):
                self.stdout.write(self.style.ERROR(f'  ✗ [{e["regla"]}] {e["campo"]}: {e["detalle"]}'))
            for a in g.validacion.get('advertencias', []):
                self.stdout.write(self.style.WARNING(f'  ! [{a["regla"]}] {a["campo"]}: {a["detalle"]}'))
