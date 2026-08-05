# Generado a mano — agrega el flag de integración con Misael Kids.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('documentos', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='documentopaciente',
            name='compartir_misael_kids',
            field=models.BooleanField(
                default=False,
                verbose_name='Compartir con Misael Kids',
                help_text='Visible para la educadora del jardín como plan de trabajo del niño.',
            ),
        ),
    ]
