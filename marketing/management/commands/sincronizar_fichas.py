from django.core.management.base import BaseCommand, CommandError

from marketing.sincronizacion import sincronizar_fichas_centro


class Command(BaseCommand):
    help = ('Crea/actualiza las fichas de Centro Misael desde las páginas públicas de servicios y las sedes. '
            'Las fichas nuevas quedan SIN aprobar.')

    def handle(self, *args, **options):
        try:
            r = sincronizar_fichas_centro()
        except ValueError as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(
            f'Creadas: {r["creadas"]} | Actualizadas: {r["actualizadas"]} | '
            f'Sin cambios: {r["sin_cambios"]} | Conservadas (editadas a mano): {r["conservadas_editadas"]}'
        ))
        if r['creadas'] or r['actualizadas']:
            self.stdout.write('Revísalas y apruébalas en Admin > Marketing > Fichas de contenido.')
