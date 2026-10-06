from datetime import date

from django.core.management.base import BaseCommand, CommandError

from asistencia.services import generar_ausentes


class Command(BaseCommand):
    help = (
        "Genera registros AUSENTE para los bloques de horario ya terminados en los que "
        "el profesional no marcó entrada. Es idempotente: se recomienda ejecutarlo cada "
        "hora por cron (ej: 5 * * * * cd /app && python manage.py generar_ausentes)."
    )

    def add_arguments(self, parser):
        parser.add_argument('--fecha', help='YYYY-MM-DD (por defecto: hoy)')
        parser.add_argument('--incluir-sin-enrolar', action='store_true',
                            help='Incluir profesionales que aún no registraron su rostro')

    def handle(self, *args, **opts):
        fecha = None
        if opts['fecha']:
            try:
                fecha = date.fromisoformat(opts['fecha'])
            except ValueError:
                raise CommandError('Formato de fecha inválido, usa YYYY-MM-DD')
        n = generar_ausentes(fecha=fecha, incluir_sin_enrolar=opts['incluir_sin_enrolar'])
        self.stdout.write(self.style.SUCCESS(f'Ausencias creadas: {n}'))
