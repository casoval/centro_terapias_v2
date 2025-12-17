# facturacion/migrations/0002_pago_anulado_fields.py

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('facturacion', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='pago',
            name='anulado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='pago',
            name='motivo_anulacion',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='pago',
            name='anulado_por',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='pagos_anulados',
                to=settings.AUTH_USER_MODEL
            ),
        ),
        migrations.AddField(
            model_name='pago',
            name='fecha_anulacion',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]