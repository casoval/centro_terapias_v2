"""
Datos para las vigencias por fecha: nada de lo ya configurado cambia.

  - Plantillas y reglas existentes ya quedaron con vigente_desde = 2000-01-01 ("desde siempre").
  - Cada asignación con horario propio recibe un periodo abierto desde esa misma fecha.
"""
import datetime

from django.db import migrations

DESDE_SIEMPRE = datetime.date(2000, 1, 1)


def crear_periodos(apps, schema_editor):
    Config = apps.get_model('asistencia', 'ConfigAsistencia')
    Periodo = apps.get_model('asistencia', 'PeriodoHorarioPropio')
    for cfg in Config.objects.filter(personalizado=True):
        if not Periodo.objects.filter(config=cfg).exists():
            Periodo.objects.create(config=cfg, desde=DESDE_SIEMPRE, hasta=None)


class Migration(migrations.Migration):

    dependencies = [
        ('asistencia', '0010_vigencias'),
    ]

    operations = [
        migrations.RunPython(crear_periodos, migrations.RunPython.noop),
    ]
