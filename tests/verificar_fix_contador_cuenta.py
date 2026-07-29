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
from agenda.models import Sesion
from facturacion.models import Pago, MetodoPago, DetallePagoMasivo
from facturacion.services import AccountService


def main():
    user, _ = User.objects.get_or_create(username='test_perf', defaults={'is_superuser': True, 'is_staff': True})
    sucursal, _ = Sucursal.objects.get_or_create(nombre='Sucursal Test', defaults={'activa': True, 'direccion': 'Calle Falsa 123'})
    servicio, _ = TipoServicio.objects.get_or_create(nombre='Servicio Test', defaults={'activo': True, 'color': '#3498db', 'duracion_minutos': 45, 'costo_base': Decimal('100.00')})
    profesional, _ = Profesional.objects.get_or_create(nombre='Prof', apellido='Test', defaults={'activo': True})
    profesional.sucursales.add(sucursal)
    profesional.servicios.add(servicio)
    paciente, _ = Paciente.objects.get_or_create(
        nombre='PacienteCuenta', apellido='Test',
        defaults={'estado': 'activo', 'fecha_nacimiento': date(2015, 1, 1), 'genero': 'M'}
    )
    paciente.sucursales.add(sucursal)
    metodo, _ = MetodoPago.objects.get_or_create(nombre='Efectivo')

    # 2 sesiones REALIZADAS con costo:
    # - sesion_a: se paga con un PAGO DIRECTO normal
    # - sesion_b: se paga con un PAGO MASIVO (recibo que cubre varias sesiones)
    sesion_a, _ = Sesion.objects.get_or_create(
        paciente=paciente, fecha=date(2050, 1, 1), hora_inicio=time(9, 0),
        defaults=dict(servicio=servicio, profesional=profesional, sucursal=sucursal,
                      hora_fin=time(9, 45), duracion_minutos=45, estado='realizada',
                      monto_cobrado=Decimal('100.00'), creada_por=user)
    )
    sesion_b, _ = Sesion.objects.get_or_create(
        paciente=paciente, fecha=date(2050, 1, 2), hora_inicio=time(9, 0),
        defaults=dict(servicio=servicio, profesional=profesional, sucursal=sucursal,
                      hora_fin=time(9, 45), duracion_minutos=45, estado='realizada',
                      monto_cobrado=Decimal('100.00'), creada_por=user)
    )

    Pago.objects.get_or_create(
        numero_recibo='CUENTA-TEST-0001', paciente=paciente, sesion=sesion_a,
        defaults=dict(fecha_pago=date.today(), monto=Decimal('100'), metodo_pago=metodo,
                      concepto='Pago directo sesion_a', registrado_por=user)
    )
    pago_masivo, _ = Pago.objects.get_or_create(
        numero_recibo='CUENTA-TEST-0002', paciente=paciente,
        defaults=dict(fecha_pago=date.today(), monto=Decimal('100'), metodo_pago=metodo,
                      concepto='Pago masivo sesion_b', registrado_por=user)
    )
    DetallePagoMasivo.objects.get_or_create(
        pago=pago_masivo, tipo='sesion', sesion=sesion_b,
        defaults=dict(monto=Decimal('100'), concepto='Detalle sesion_b via pago masivo')
    )

    print("=== Ejecutando AccountService.update_balance ===")
    cuenta = AccountService.update_balance(paciente)

    print(f"  total_sesiones_normales_real = {cuenta.total_sesiones_normales_real} (esperado 200: costo de ambas sesiones)")
    print(f"  pagos_sesiones (dinero)      = {cuenta.pagos_sesiones} (esperado 200: 100 directo + 100 masivo)")
    print(f"  num_sesiones_realizadas_pendientes = {cuenta.num_sesiones_realizadas_pendientes} (esperado 0: ambas están pagadas)")

    assert cuenta.total_sesiones_normales_real == Decimal('200.00'), "❌ Cambió el costo total (no debería)"
    assert cuenta.pagos_sesiones == Decimal('200'), "❌ El saldo en dinero está mal (no debería haber cambiado, ya estaba bien)"
    assert cuenta.num_sesiones_realizadas_pendientes == 0, (
        f"❌ ANTES del fix esto daba 1 (no reconocía el pago masivo de sesion_b). "
        f"Ahora dio {cuenta.num_sesiones_realizadas_pendientes}, debería ser 0."
    )
    print("  ✅ El contador ahora reconoce correctamente la sesión pagada por pago masivo")
    print("  ✅ El saldo en dinero sigue siendo el mismo de antes (no se tocó nada financiero)")

    print("\n🎉 CORRECCIÓN DE num_sesiones_realizadas_pendientes VERIFICADA")


if __name__ == '__main__':
    main()
