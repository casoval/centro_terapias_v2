"""Paso 1/3 — crea las tablas nuevas (plantillas y bloques) SIN tocar las viejas."""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('asistencia', '0004_registroasistencia_registrado_por'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='enrolamientofacial',
            name='foto_referencia',
            field=models.ImageField(blank=True, help_text='Foto tomada al enrolar, para revision del administrador', null=True, upload_to='asistencia/enrolamiento/'),
        ),
        migrations.AddField(
            model_name='registroasistencia',
            name='precision_metros',
            field=models.FloatField(blank=True, help_text='Precision reportada por el GPS del dispositivo', null=True),
        ),
        migrations.AlterField(
            model_name='registroasistencia',
            name='bloque',
            field=models.CharField(blank=True, max_length=10),
        ),
        migrations.CreateModel(
            name='PlantillaHorario',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(blank=True, max_length=100)),
                ('dias', models.JSONField(default=list, help_text='Ej: ["LUN","MAR","MIE","JUE","VIE"]')),
                ('creada_en', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(blank=True, help_text='Vacio = predeterminado de la zona', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='plantillas_asistencia', to=settings.AUTH_USER_MODEL)),
                ('zona', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='plantillas', to='asistencia.zonaasistencia')),
            ],
            options={
                'verbose_name': 'Plantilla de horario',
                'verbose_name_plural': 'Plantillas de horario',
                'ordering': ['zona__nombre', 'id'],
            },
        ),
        migrations.CreateModel(
            name='BloqueHorario',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('orden', models.PositiveSmallIntegerField(default=1)),
                ('hora_entrada', models.TimeField()),
                ('hora_salida', models.TimeField()),
                ('tolerancia_minutos', models.PositiveIntegerField(default=10)),
                ('plantilla', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bloques', to='asistencia.plantillahorario')),
            ],
            options={
                'verbose_name': 'Bloque de horario',
                'verbose_name_plural': 'Bloques de horario',
                'ordering': ['orden', 'hora_entrada'],
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='BloqueFechaEspecial',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('orden', models.PositiveSmallIntegerField(default=1)),
                ('hora_entrada', models.TimeField()),
                ('hora_salida', models.TimeField()),
                ('tolerancia_minutos', models.PositiveIntegerField(default=10)),
                ('fecha_especial', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bloques', to='asistencia.fechaespecial')),
            ],
            options={
                'verbose_name': 'Bloque de fecha especial',
                'verbose_name_plural': 'Bloques de fecha especial',
                'ordering': ['orden', 'hora_entrada'],
                'abstract': False,
            },
        ),
    ]
