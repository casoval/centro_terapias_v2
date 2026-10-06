from datetime import date

from django.core.management.base import BaseCommand, CommandError

from asistencia.tareas import enviar_reporte_diario


class Command(BaseCommand):
    help = "Envía a RRHH el reporte CSV de asistencia del día (ejecutar al cierre de jornada)."

    def add_arguments(self, parser):
        parser.add_argument('--fecha', help='YYYY-MM-DD (por defecto: hoy)')

    def handle(self, *args, **opts):
        fecha = None
        if opts['fecha']:
            try:
                fecha = date.fromisoformat(opts['fecha'])
            except ValueError:
                raise CommandError('Formato de fecha inválido, usa YYYY-MM-DD')
        self.stdout.write(enviar_reporte_diario(fecha))
