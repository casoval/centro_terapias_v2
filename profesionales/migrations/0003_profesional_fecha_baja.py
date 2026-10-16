from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('profesionales', '0002_profesional_foto'),
    ]

    operations = [
        migrations.AddField(
            model_name='profesional',
            name='fecha_baja',
            field=models.DateField(blank=True, null=True, help_text='Día en que se desactivó. La baja no es retroactiva: los informes de asistencia anteriores a esta fecha siguen mostrando al profesional. Se completa sola.'),
        ),
    ]
