import os
import sys
from datetime import date, time
from decimal import Decimal

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.contrib.auth.models import User
from servicios.models import Sucursal, TipoServicio
from profesionales.models import Profesional
from pacientes.models import Paciente
from agenda.models import Proyecto
from facturacion.models import Pago, MetodoPago, DetallePagoMasivo
from facturacion.services import PaymentService


def main():
    user, _ = User.objects.get_or_create(username='test_perf', defaults={'is_superuser': True, 'is_staff': True})
    sucursal, _ = Sucursal.objects.get_or_create(nombre='Sucursal Test', defaults={'activa': True, 'direccion': 'x'})
    servicio, _ = TipoServicio.objects.get_or_create(nombre='Servicio Test', defaults={'activo': True, 'color': '#3498db', 'duracion_minutos': 45, 'costo_base': Decimal('100.00')})
    profesional, _ = Profesional.objects.get_or_create(nombre='Prof', apellido='Test', defaults={'activo': True})
    paciente, _ = Paciente.objects.get_or_create(
        nombre='PacienteProyecto', apellido='Test',
        defaults={'estado': 'activo', 'fecha_nacimiento': date(2015, 1, 1), 'genero': 'M'}
    )
    paciente.sucursales.add(sucursal)
    metodo, _ = MetodoPago.objects.get_or_create(nombre='Efectivo')

    # Proyecto de costo 100
    proyecto, _ = Proyecto.objects.get_or_create(
        codigo='TEST-PROY-001', paciente=paciente,
        defaults=dict(
            nombre='Proyecto test', tipo='evaluacion', servicio_base=servicio,
            profesional_responsable=profesional, sucursal=sucursal,
            fecha_inicio=date(2070, 1, 1), costo_total=Decimal('100.00'),
            estado='en_progreso', creado_por=user,
        )
    )

    # Pagado 100% mediante un PAGO MASIVO (no directo)
    pago_masivo, _ = Pago.objects.get_or_create(
        numero_recibo='PROY-MASIVO-0001', paciente=paciente,
        defaults=dict(fecha_pago=date.today(), monto=Decimal('100'), metodo_pago=metodo,
                      concepto='Pago masivo proyecto', registrado_por=user)
    )
    DetallePagoMasivo.objects.get_or_create(
        pago=pago_masivo, tipo='proyecto', proyecto=proyecto,
        defaults=dict(monto=Decimal('100'), concepto='Detalle proyecto via pago masivo')
    )

    print("=== TEST 1: ajuste automático de costo_total al marcar 'pago completo' ===")
    print(f"  costo_total ANTES = {proyecto.costo_total} (ya estaba pagado 100 vía masivo)")

    # Ahora llega un pago DIRECTO adicional de 20, marcado como "pago completo"
    resultado = PaymentService.process_payment(
        user=user, paciente=paciente, monto_total=Decimal('20'),
        metodo_pago_id=metodo.id, fecha_pago=date.today(),
        tipo_pago='proyecto', referencia_id=proyecto.id,
        es_pago_completo=True, observaciones='Pago directo adicional',
    )
    proyecto.refresh_from_db()
    print(f"  costo_total DESPUÉS = {proyecto.costo_total} (esperado 120: 100 masivo + 20 directo)")
    assert resultado['success'], f"process_payment falló: {resultado}"
    assert proyecto.costo_total == Decimal('120'), (
        f"❌ El costo_total quedó en {proyecto.costo_total}. "
        f"ANTES del fix hubiera quedado en 20 (perdiendo el pago masivo de 100)."
    )
    print("  ✅ El costo_total ahora incluye correctamente el pago masivo + el directo")

    print("\n=== TEST 2: validación de devolución con proyecto pagado por masivo ===")
    # Nuevo proyecto pagado 100% SOLO por pago masivo, sin pagos directos
    proyecto2, _ = Proyecto.objects.get_or_create(
        codigo='TEST-PROY-002', paciente=paciente,
        defaults=dict(
            nombre='Proyecto test 2', tipo='evaluacion', servicio_base=servicio,
            profesional_responsable=profesional, sucursal=sucursal,
            fecha_inicio=date(2070, 2, 1), costo_total=Decimal('80.00'),
            estado='en_progreso', creado_por=user,
        )
    )
    pago_masivo2, _ = Pago.objects.get_or_create(
        numero_recibo='PROY-MASIVO-0002', paciente=paciente,
        defaults=dict(fecha_pago=date.today(), monto=Decimal('80'), metodo_pago=metodo,
                      concepto='Pago masivo proyecto 2', registrado_por=user)
    )
    DetallePagoMasivo.objects.get_or_create(
        pago=pago_masivo2, tipo='proyecto', proyecto=proyecto2,
        defaults=dict(monto=Decimal('80'), concepto='Detalle proyecto 2 via pago masivo')
    )

    try:
        resultado_devolucion = PaymentService.process_refund(
            user=user, paciente=paciente, monto_devolucion=Decimal('80'),
            metodo_pago_id=metodo.id, fecha_devolucion=date.today(),
            tipo_devolucion='proyecto', referencia_id=proyecto2.id,
            motivo='Devolución de prueba',
        )
        print(f"  Devolución de 80 (pagados 100% vía masivo) -> success={resultado_devolucion['success']} (esperado True)")
        assert resultado_devolucion['success']
        print("  ✅ La devolución ahora se permite correctamente (antes del fix hubiera sido bloqueada)")
    except Exception as e:
        print(f"  ❌ La devolución fue rechazada: {e}")
        raise

    print("\n🎉 TODOS LOS FIXES DE ESCRITURA/VALIDACIÓN DE PAGOS VERIFICADOS")


if __name__ == '__main__':
    main()
