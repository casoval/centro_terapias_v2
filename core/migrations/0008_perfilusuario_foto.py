import cloudinary.models
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_perfilusuario_telefono'),
    ]

    operations = [
        migrations.AddField(
            model_name='perfilusuario',
            name='foto',
            field=cloudinary.models.CloudinaryField(blank=True, help_text='Foto del usuario (opcional, se optimizará automáticamente)', max_length=255, null=True, verbose_name='foto'),
        ),
    ]
