"""Paso 3/3 — quita los campos viejos de las reglas (ya convertidos en tramos)."""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('asistencia', '0013_retraso_tramos_datos'),
    ]

    operations = [
        migrations.RemoveField(model_name='reglasasistencia', name='minutos_medio_dia'),
        migrations.RemoveField(model_name='reglasasistencia', name='minutos_dia_completo'),
    ]
