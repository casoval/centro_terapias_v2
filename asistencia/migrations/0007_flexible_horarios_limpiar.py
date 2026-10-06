"""Paso 3/3 — elimina el esquema viejo (ya convertido en el paso 2)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('asistencia', '0006_flexible_horarios_datos'),
    ]

    operations = [
        migrations.RemoveField(model_name='configasistencia', name='dias_continuo_custom'),
        migrations.RemoveField(model_name='configasistencia', name='dias_partido_custom'),
        migrations.RemoveField(model_name='configasistencia', name='hora_entrada_custom'),
        migrations.RemoveField(model_name='configasistencia', name='hora_entrada_tarde_custom'),
        migrations.RemoveField(model_name='configasistencia', name='hora_salida_custom'),
        migrations.RemoveField(model_name='configasistencia', name='hora_salida_tarde_custom'),
        migrations.RemoveField(model_name='configasistencia', name='tolerancia_custom'),
        migrations.RemoveField(model_name='configasistencia', name='tolerancia_tarde_custom'),
        migrations.RemoveField(model_name='fechaespecial', name='hora_entrada_especial'),
        migrations.RemoveField(model_name='fechaespecial', name='hora_entrada_tarde_especial'),
        migrations.RemoveField(model_name='fechaespecial', name='hora_salida_especial'),
        migrations.RemoveField(model_name='fechaespecial', name='hora_salida_tarde_especial'),
        migrations.RemoveField(model_name='fechaespecial', name='tolerancia_especial'),
        migrations.RemoveField(model_name='fechaespecial', name='tolerancia_tarde_especial'),
        migrations.AlterField(
            model_name='fechaespecial',
            name='tipo_horario',
            field=models.CharField(choices=[('horario', 'Horario especial'), ('libre', 'Dia libre')], default='horario', max_length=10),
        ),
        migrations.DeleteModel(name='HorarioPredeterminado'),
    ]
