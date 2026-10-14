"""Paso 1/3 — agrega segundos de retraso por registro, tramos de descuento y permisos justificados."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('asistencia', '0011_vigencias_datos'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='registroasistencia',
            name='segundos_tarde',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='registroasistencia',
            name='segundos_acumulables',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='registroasistencia',
            name='minutos_tardanza',
            field=models.IntegerField(default=0),
        ),
        migrations.CreateModel(
            name='TramoDescuento',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('hasta_minutos', models.DecimalField(blank=True, decimal_places=2, help_text='Hasta cuántos minutos acumulados (inclusive). Vacío = sin tope.', max_digits=6, null=True)),
                ('dias', models.DecimalField(decimal_places=2, default=0, help_text='Días de descuento (0, 0.5, 1, 2, 3...).', max_digits=4)),
                ('regla', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tramos', to='asistencia.reglasasistencia')),
            ],
            options={
                'verbose_name': 'Tramo de descuento',
                'verbose_name_plural': 'Tramos de descuento',
                'ordering': ['hasta_minutos'],
            },
        ),
        migrations.CreateModel(
            name='PermisoAsistencia',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateField()),
                ('bloque', models.CharField(blank=True, help_text='Vacío = todo el día; "1", "2"... = solo ese bloque', max_length=2)),
                ('tipo', models.CharField(choices=[('medico', 'Certificado médico'), ('autorizado', 'Permiso autorizado por escrito'), ('otro', 'Otro justificativo escrito')], default='medico', max_length=12)),
                ('detalle', models.TextField(help_text='Qué justificativo se presentó (certificado de..., nota firmada por..., etc.)')),
                ('comprobante', models.FileField(blank=True, null=True, upload_to='asistencia/justificativos/%Y/%m/')),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('registrado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='permisos_asistencia_registrados', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='permisos_asistencia', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Permiso de asistencia',
                'verbose_name_plural': 'Permisos de asistencia',
                'ordering': ['-fecha', 'user_id'],
                'unique_together': {('user', 'fecha', 'bloque')},
            },
        ),
    ]
