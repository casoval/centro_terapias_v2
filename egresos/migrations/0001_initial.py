# egresos/migrations/0001_initial.py
# Migración inicial — generada manualmente.
# Ejecutar: python manage.py migrate egresos

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('facturacion', '0014_cuentacorriente_ingreso_neto_centro_and_more'),
        ('profesionales', '0002_profesional_foto'),
        ('servicios', '0005_tiposervicio_es_servicio_externo_and_more'),
        ('agenda', '0012_permisoedicionsesion'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── CategoriaEgreso ───────────────────────────────────────────────────
        migrations.CreateModel(
            name='CategoriaEgreso',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=100, unique=True, verbose_name='Nombre')),
                ('tipo', models.CharField(
                    choices=[
                        ('arriendo', 'Arriendo / Alquiler'),
                        ('servicios_basicos', 'Servicios Básicos'),
                        ('personal', 'Personal Interno'),
                        ('honorarios', 'Honorarios Profesionales'),
                        ('equipamiento', 'Equipamiento y Materiales'),
                        ('mantenimiento', 'Mantenimiento'),
                        ('marketing', 'Marketing y Publicidad'),
                        ('impuesto', 'Impuestos y Tasas'),
                        ('seguro', 'Seguros'),
                        ('capacitacion', 'Capacitación'),
                        ('otro', 'Otro'),
                    ],
                    max_length=30, verbose_name='Tipo'
                )),
                ('descripcion', models.TextField(blank=True, verbose_name='Descripción')),
                ('activo', models.BooleanField(default=True, verbose_name='Activo')),
                ('es_honorario_profesional', models.BooleanField(default=False, verbose_name='Es pago de honorarios')),
            ],
            options={
                'verbose_name': 'Categoría de Egreso',
                'verbose_name_plural': 'Categorías de Egreso',
                'ordering': ['tipo', 'nombre'],
            },
        ),

        # ── Proveedor ─────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Proveedor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=200, verbose_name='Nombre / Razón Social')),
                ('tipo', models.CharField(
                    choices=[
                        ('empresa', 'Empresa / Institución'),
                        ('profesional', 'Profesional Externo'),
                        ('persona', 'Persona Natural'),
                    ],
                    max_length=20, verbose_name='Tipo'
                )),
                ('nit_ci', models.CharField(blank=True, max_length=20, verbose_name='NIT / CI')),
                ('telefono', models.CharField(blank=True, max_length=20, verbose_name='Teléfono')),
                ('email', models.EmailField(blank=True, verbose_name='Email')),
                ('banco', models.CharField(blank=True, max_length=100, verbose_name='Banco')),
                ('numero_cuenta', models.CharField(blank=True, max_length=50, verbose_name='N° de Cuenta')),
                ('activo', models.BooleanField(default=True, verbose_name='Activo')),
                ('observaciones', models.TextField(blank=True, verbose_name='Observaciones')),
                ('profesional', models.OneToOneField(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='proveedor_egreso',
                    to='profesionales.profesional',
                    verbose_name='Profesional del sistema'
                )),
            ],
            options={
                'verbose_name': 'Proveedor',
                'verbose_name_plural': 'Proveedores',
                'ordering': ['nombre'],
            },
        ),

        # ── Egreso ────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Egreso',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('numero_egreso', models.CharField(max_length=20, unique=True, verbose_name='N° Egreso')),
                ('fecha', models.DateField(verbose_name='Fecha de pago')),
                ('concepto', models.CharField(max_length=300, verbose_name='Concepto')),
                ('monto', models.DecimalField(decimal_places=0, max_digits=10, verbose_name='Monto (Bs.)')),
                ('periodo_mes', models.PositiveSmallIntegerField(
                    blank=True, null=True,
                    choices=[(i, str(i).zfill(2)) for i in range(1, 13)],
                    verbose_name='Período - Mes'
                )),
                ('periodo_anio', models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='Período - Año')),
                ('numero_transaccion', models.CharField(blank=True, max_length=100, verbose_name='N° Transacción / Cheque')),
                ('numero_documento_proveedor', models.CharField(blank=True, max_length=50, verbose_name='N° Doc. Proveedor')),
                ('comprobante', models.FileField(blank=True, upload_to='egresos/comprobantes/%Y/%m/', verbose_name='Comprobante')),
                ('observaciones', models.TextField(blank=True, verbose_name='Observaciones')),
                ('fecha_registro', models.DateTimeField(auto_now_add=True, verbose_name='Fecha de registro')),
                ('anulado', models.BooleanField(default=False, verbose_name='Anulado')),
                ('motivo_anulacion', models.TextField(blank=True, verbose_name='Motivo de anulación')),
                ('fecha_anulacion', models.DateTimeField(blank=True, null=True, verbose_name='Fecha de anulación')),
                ('categoria', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='egresos', to='egresos.categoriaegreso', verbose_name='Categoría')),
                ('proveedor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='egresos', to='egresos.proveedor', verbose_name='Proveedor / Beneficiario')),
                ('metodo_pago', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='facturacion.metodopago', verbose_name='Método de Pago')),
                ('sucursal', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='servicios.sucursal', verbose_name='Sucursal')),
                ('registrado_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='egresos_registrados', to=settings.AUTH_USER_MODEL, verbose_name='Registrado por')),
                ('anulado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='egresos_anulados', to=settings.AUTH_USER_MODEL, verbose_name='Anulado por')),
                ('sesiones_cubiertas', models.ManyToManyField(blank=True, related_name='egreso_honorario', to='agenda.sesion', verbose_name='Sesiones cubiertas')),
            ],
            options={
                'verbose_name': 'Egreso',
                'verbose_name_plural': 'Egresos',
                'ordering': ['-fecha', '-fecha_registro'],
                'indexes': [
                    models.Index(fields=['fecha'], name='idx_egreso_fecha'),
                    models.Index(fields=['periodo_mes', 'periodo_anio'], name='idx_egreso_periodo'),
                    models.Index(fields=['anulado'], name='idx_egreso_anulado'),
                    models.Index(fields=['categoria'], name='idx_egreso_categoria'),
                ],
            },
        ),

        # ── EgresoRecurrente ──────────────────────────────────────────────────
        migrations.CreateModel(
            name='EgresoRecurrente',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('concepto', models.CharField(max_length=300, verbose_name='Concepto')),
                ('monto_estimado', models.DecimalField(decimal_places=0, max_digits=10, verbose_name='Monto estimado (Bs.)')),
                ('frecuencia', models.CharField(
                    choices=[
                        ('mensual', 'Mensual'), ('bimestral', 'Bimestral'),
                        ('trimestral', 'Trimestral'), ('semestral', 'Semestral'),
                        ('anual', 'Anual'),
                    ],
                    default='mensual', max_length=20, verbose_name='Frecuencia'
                )),
                ('dia_vencimiento', models.PositiveSmallIntegerField(default=1, verbose_name='Día de vencimiento')),
                ('activo', models.BooleanField(default=True, verbose_name='Activo')),
                ('fecha_inicio', models.DateField(verbose_name='Fecha de inicio')),
                ('fecha_fin', models.DateField(blank=True, null=True, verbose_name='Fecha de fin')),
                ('ultimo_generado', models.DateField(blank=True, null=True, verbose_name='Último generado')),
                ('observaciones', models.TextField(blank=True, verbose_name='Observaciones')),
                ('categoria', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='egresos.categoriaegreso', verbose_name='Categoría')),
                ('proveedor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='egresos.proveedor', verbose_name='Proveedor')),
                ('metodo_pago_default', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='facturacion.metodopago', verbose_name='Método de pago por defecto')),
                ('sucursal', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='servicios.sucursal', verbose_name='Sucursal')),
            ],
            options={
                'verbose_name': 'Egreso Recurrente',
                'verbose_name_plural': 'Egresos Recurrentes',
                'ordering': ['categoria__tipo', 'concepto'],
            },
        ),

        # ── ResumenFinanciero ─────────────────────────────────────────────────
        migrations.CreateModel(
            name='ResumenFinanciero',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mes', models.PositiveSmallIntegerField(choices=[(i, str(i).zfill(2)) for i in range(1, 13)], verbose_name='Mes')),
                ('anio', models.PositiveSmallIntegerField(verbose_name='Año')),
                ('ingresos_brutos', models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Ingresos brutos')),
                ('total_devoluciones', models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Total devoluciones')),
                ('ingresos_netos', models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Ingresos netos')),
                ('egresos_arriendo', models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Arriendo / Alquiler')),
                ('egresos_servicios_basicos', models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Servicios básicos')),
                ('egresos_personal', models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Personal interno')),
                ('egresos_honorarios', models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Honorarios profesionales')),
                ('egresos_equipamiento', models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Equipamiento y materiales')),
                ('egresos_mantenimiento', models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Mantenimiento')),
                ('egresos_marketing', models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Marketing y publicidad')),
                ('egresos_impuestos', models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Impuestos y tasas')),
                ('egresos_seguros', models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Seguros')),
                ('egresos_capacitacion', models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Capacitación')),
                ('egresos_otros', models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Otros egresos')),
                ('total_egresos', models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Total egresos')),
                ('resultado_neto', models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Resultado neto')),
                ('margen_porcentaje', models.DecimalField(decimal_places=2, default=0, max_digits=5, verbose_name='Margen (%)')),
                ('ultima_actualizacion', models.DateTimeField(auto_now=True, verbose_name='Última actualización')),
                ('sucursal', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='servicios.sucursal', verbose_name='Sucursal')),
            ],
            options={
                'verbose_name': 'Resumen Financiero',
                'verbose_name_plural': 'Resúmenes Financieros',
                'ordering': ['-anio', '-mes'],
                'unique_together': {('mes', 'anio', 'sucursal')},
            },
        ),
    ]