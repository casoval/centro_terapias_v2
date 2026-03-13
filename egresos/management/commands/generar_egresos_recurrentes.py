# egresos/management/commands/generar_egresos_recurrentes.py
"""
Management command para generar los egresos del mes actual
a partir de las plantillas EgresoRecurrente activas.

Uso:
    python manage.py generar_egresos_recurrentes
    python manage.py generar_egresos_recurrentes --mes 3 --anio 2025
    python manage.py generar_egresos_recurrentes --dry-run

Recomendado: ejecutar como cron el día 1 de cada mes.
    0 6 1 * * /ruta/al/venv/bin/python manage.py generar_egresos_recurrentes
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db.models import Q
from datetime import date, timedelta
import calendar


class Command(BaseCommand):
    help = 'Genera egresos del mes actual desde las plantillas de egresos recurrentes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--mes',
            type=int,
            default=None,
            help='Mes a procesar (1-12). Default: mes actual.'
        )
        parser.add_argument(
            '--anio',
            type=int,
            default=None,
            help='Año a procesar. Default: año actual.'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Simula el proceso sin crear egresos reales.'
        )
        parser.add_argument(
            '--usuario',
            type=str,
            default=None,
            help='Username del usuario que registra. Default: primer superusuario.'
        )

    def handle(self, *args, **options):
        from egresos.models import EgresoRecurrente, Egreso
        from egresos.services import ResumenFinancieroService

        hoy  = date.today()
        mes  = options['mes']  or hoy.month
        anio = options['anio'] or hoy.year
        dry_run = options['dry_run']

        # Resolver el usuario registrador
        usuario_param = options.get('usuario')
        if usuario_param:
            try:
                usuario = User.objects.get(username=usuario_param)
            except User.DoesNotExist:
                self.stderr.write(f'❌ Usuario "{usuario_param}" no existe.')
                return
        else:
            usuario = User.objects.filter(is_superuser=True).first()
            if not usuario:
                self.stderr.write('❌ No hay superusuarios. Use --usuario.')
                return

        # Fecha del período
        fecha_periodo = date(anio, mes, 1)

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f'\n{"[DRY-RUN] " if dry_run else ""}'
                f'Generando egresos recurrentes para '
                f'{str(mes).zfill(2)}/{anio}'
            )
        )

        # Obtener plantillas activas que aplican para este mes
        plantillas = EgresoRecurrente.objects.filter(
            activo=True,
            fecha_inicio__lte=fecha_periodo,
        ).filter(
            Q(fecha_fin__isnull=True) | Q(fecha_fin__gte=fecha_periodo)
        ).select_related('categoria', 'proveedor', 'metodo_pago_default')

        creados   = 0
        omitidos  = 0
        errores   = 0

        for plantilla in plantillas:
            # Verificar si ya existe un egreso para esta plantilla en este período
            # (identificado por misma categoría, proveedor y período)
            ya_existe = Egreso.objects.filter(
                categoria=plantilla.categoria,
                proveedor=plantilla.proveedor,
                periodo_mes=mes,
                periodo_anio=anio,
                anulado=False,
                concepto__icontains=plantilla.concepto[:30],  # heurística
            ).exists()

            if ya_existe:
                self.stdout.write(
                    f'  ⏩ OMITIDO (ya existe): {plantilla.concepto}'
                )
                omitidos += 1
                continue

            # Calcular fecha de vencimiento (capped a último día del mes)
            ultimo_dia = calendar.monthrange(anio, mes)[1]
            dia = min(plantilla.dia_vencimiento, ultimo_dia)
            fecha_egreso = date(anio, mes, dia)

            if dry_run:
                self.stdout.write(
                    f'  🔍 [DRY-RUN] Generaría: {plantilla.concepto} — '
                    f'Bs. {plantilla.monto_estimado} — Fecha: {fecha_egreso}'
                )
                creados += 1
                continue

            try:
                egreso = Egreso.objects.create(
                    categoria=plantilla.categoria,
                    proveedor=plantilla.proveedor,
                    concepto=f"{plantilla.concepto} — {_mes_nombre(mes)} {anio}",
                    monto=plantilla.monto_estimado,
                    fecha=fecha_egreso,
                    metodo_pago=plantilla.metodo_pago_default,
                    periodo_mes=mes,
                    periodo_anio=anio,
                    sucursal=plantilla.sucursal,
                    observaciones=f'Generado automáticamente desde plantilla recurrente #{plantilla.id}',
                    registrado_por=usuario,
                )

                # Actualizar fecha de último generado en la plantilla
                plantilla.ultimo_generado = fecha_egreso
                plantilla.save(update_fields=['ultimo_generado'])

                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✅ Creado: {egreso.numero_egreso} — '
                        f'{egreso.concepto} — Bs. {egreso.monto}'
                    )
                )
                creados += 1

            except Exception as e:
                self.stderr.write(
                    f'  ❌ Error en "{plantilla.concepto}": {str(e)}'
                )
                errores += 1

        # Recalcular resumen financiero del mes
        if creados > 0 and not dry_run:
            ResumenFinancieroService.recalcular_mes(mes, anio)

        # Resumen final
        self.stdout.write('\n' + '─' * 50)
        self.stdout.write(
            self.style.SUCCESS(
                f'{"[DRY-RUN] " if dry_run else ""}'
                f'Proceso completado: '
                f'{creados} creados | {omitidos} omitidos | {errores} errores'
            )
        )


def _mes_nombre(mes):
    nombres = [
        '', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
        'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'
    ]
    return nombres[mes]