import archivos_centro.models
import archivos_centro.storage_backends
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('archivos_centro', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='archivocentro',
            name='archivo',
            field=models.FileField(
                storage=archivos_centro.storage_backends.get_archivos_centro_storage(),
                upload_to='archivos_centro/%Y/%m/',
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=[
                            'pdf', 'doc', 'docx', 'odt', 'txt', 'jpg', 'jpeg', 'png',
                            'webp', 'xls', 'xlsx', 'csv', 'ppt', 'pptx', 'zip', 'rar',
                        ]
                    ),
                    archivos_centro.models.validar_tamano_archivo,
                ],
            ),
        ),
    ]
