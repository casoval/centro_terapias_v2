import os
import sys
from datetime import date, time, timedelta
from decimal import Decimal

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, reset_queries
from django.test import Client
from django.conf import settings

settings.DEBUG = True

from servicios.models import Sucursal, TipoServicio
from profesionales.models import Profesional
from pacientes.models import Paciente
from agenda.models import Sesion, Mensualidad, ServicioProfesionalMensualidad
from facturacion.models import Pago, MetodoPago, DetallePagoMasivo
from documentos.models import DocumentoPaciente


def main():
    user = User.objects.get(username='test_perf')
    sucursal = Sucursal.objects.get(nombre='Sucursal Test')
    servicio = TipoServicio.objects.get(nombre='Servicio Test')
    profesional = Profesional.objects.get(nombre='Prof', apellido='Test')
    paciente = Paciente.objects.get(nombre='Paciente', apellido='Test')
    metodo, _ = MetodoPago.objects.get_or_create(nombre='Efectivo')

    mensualidad, created = Mensualidad.objects.get_or_create(
        codigo='TESTPERF-MEN-001',
        defaults=dict(
            paciente=paciente, sucursal=sucursal, mes=1, anio=2099,
            costo_mensual=Decimal('400.00'), creada_por=user,
        )
    )
    ServicioProfesionalMensualidad.objects.get_or_create(
        mensualidad=mensualidad, servicio=servicio, profesional=profesional
    )

    # 4 sesiones ligadas a la mensualidad, 2 de ellas "realizada"
    for i in range(4):
        Sesion.objects.get_or_create(
            paciente=paciente, fecha=date(2099, 1, 5 + i), hora_inicio=time(9, 0),
            defaults=dict(
                servicio=servicio, profesional=profesional, sucursal=sucursal,
                hora_fin=time(9, 45), duracion_minutos=45,
                estado='realizada' if i < 2 else 'programada',
                monto_cobrado=Decimal('100.00'), creada_por=user,
                mensualidad=mensualidad,
            )
        )

    # 3 documentos ligados a la mensualidad (para forzar el fan-out si el
    # fix no fuera correcto: 4 sesiones x 3 documentos = 12 filas del JOIN)
    for i in range(3):
        DocumentoPaciente.objects.get_or_create(
            paciente=paciente, mensualidad=mensualidad, tipo='mensualidad',
            titulo=f'Doc test {i}',
            defaults=dict(
                archivo=SimpleUploadedFile(f'doc{i}.pdf', b'contenido', content_type='application/pdf'),
                subido_por=user,
            )
        )

    # Pago directo (100) + pago masivo (100) => total_pagado esperado = 200
    Pago.objects.get_or_create(
        numero_recibo='TESTPERF-MEN-0001', paciente=paciente, mensualidad=mensualidad,
        defaults=dict(fecha_pago=date.today(), monto=Decimal('100'), metodo_pago=metodo,
                      concepto='Pago directo mensualidad', registrado_por=user)
    )
    pago_masivo, _ = Pago.objects.get_or_create(
        numero_recibo='TESTPERF-MEN-0002', paciente=paciente,
        defaults=dict(fecha_pago=date.today(), monto=Decimal('100'), metodo_pago=metodo,
                      concepto='Pago masivo mensualidad', registrado_por=user)
    )
    DetallePagoMasivo.objects.get_or_create(
        pago=pago_masivo, tipo='mensualidad', mensualidad=mensualidad,
        defaults=dict(monto=Decimal('100'), concepto='Detalle mensualidad via pago masivo')
    )

    print("=== Verificando conteos anotados (posible fan-out) ===")
    from django.db.models import Count, Q as Qf
    qs = Mensualidad.objects.filter(id=mensualidad.id).annotate(
        num_documentos=Count('documentos', distinct=True),
        num_sesiones_anotado=Count('sesiones', distinct=True),
        num_sesiones_realizadas_anotado=Count(
            'sesiones', filter=Qf(sesiones__estado__in=['realizada', 'realizada_retraso']), distinct=True
        ),
    )
    m = qs.get()
    print(f"  num_documentos = {m.num_documentos} (esperado 3)")
    print(f"  num_sesiones_anotado = {m.num_sesiones_anotado} (esperado 4)")
    print(f"  num_sesiones_realizadas_anotado = {m.num_sesiones_realizadas_anotado} (esperado 2)")
    assert m.num_documentos == 3, f"❌ FAN-OUT detectado en num_documentos: {m.num_documentos}"
    assert m.num_sesiones_anotado == 4, f"❌ FAN-OUT detectado en num_sesiones: {m.num_sesiones_anotado}"
    assert m.num_sesiones_realizadas_anotado == 2, f"❌ FAN-OUT detectado en num_sesiones_realizadas: {m.num_sesiones_realizadas_anotado}"
    print("  ✅ Sin fan-out: los conteos son correctos pese a tener varias relaciones anotadas juntas")

    print("\n=== Verificando cachear_pagos_en_lista (proyectos y mensualidades) ===")
    from agenda.services import ProyectoMensualidadService
    instancias = ProyectoMensualidadService.cachear_pagos_en_lista([m], tipo='mensualidad')
    print(f"  total_pagado (cache) = {instancias[0].total_pagado} (esperado 200)")
    assert instancias[0].total_pagado == Decimal('200'), "❌ cachear_pagos_en_lista dio un total incorrecto"
    reset_queries()
    _ = instancias[0].total_pagado
    print(f"  queries al reconsultar total_pagado ya cacheado: {len(connection.queries)} (esperado 0)")
    assert len(connection.queries) == 0
    print("  ✅ cachear_pagos_en_lista funciona y evita queries repetidas")

    print("\n=== Ejercitando /agenda/mensualidades/ y /agenda/proyectos/ completas ===")
    client = Client()
    client.force_login(user)
    reset_queries()
    resp = client.get('/agenda/mensualidades/')
    n1 = len(connection.queries)
    print(f"  mensualidades: status={resp.status_code}, queries={n1}")
    assert resp.status_code == 200

    reset_queries()
    resp2 = client.get('/agenda/proyectos/')
    n2 = len(connection.queries)
    print(f"  proyectos: status={resp2.status_code}, queries={n2}")
    assert resp2.status_code == 200

    print("\n🎉 TODAS LAS VERIFICACIONES DE PROYECTOS/MENSUALIDADES PASARON")


if __name__ == '__main__':
    main()
