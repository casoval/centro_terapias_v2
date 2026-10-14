from django.core.management.base import BaseCommand

from asistencia.asuetos import otorgar_cumpleanos


class Command(BaseCommand):
    help = ('Otorga el asueto de cumpleaños (tipos con «Otorgar solo en el cumpleaños») a quienes cumplen años hoy. '
            'Es idempotente: puede ejecutarse todos los días. Ej.: cron  10 0 * * *  python manage.py otorgar_asuetos_cumpleanos')

    def add_arguments(self, parser):
        parser.add_argument('--fecha', help='YYYY-MM-DD (por defecto, hoy)')

    def handle(self, *args, **opts):
        from datetime import date
        fecha = date.fromisoformat(opts['fecha']) if opts.get('fecha') else None
        creados = otorgar_cumpleanos(fecha)
        self.stdout.write(f'Asuetos de cumpleaños otorgados: {creados}')
