import os
import sys
from datetime import date, time
from decimal import Decimal

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.contrib.auth.models import User
from django.test import Client
from servicios.models import Sucursal, TipoServicio
from profesionales.models import Profesional
from pacientes.models import Paciente
from agenda.models import Sesion
from facturacion.models import Pago, MetodoPago, DetallePagoMasivo


def main():
    user, _ = User.objects.get_or_create(username='test_perf', defaults={'is_superuser': True, 'is_staff': True})
    sucursal, _ = Sucursal.objects.get_or_create(nombre='Sucursal Test', defaults={'activa': True, 'direccion': 'x'})
    servicio, _ = TipoServicio.objects.get_or_create(nombre='Servicio Test', defaults={'activo': True, 'color': '#3498db', 'duracion_minutos': 45, 'costo_base': Decimal('100.00')})
    profesional, _ = Profesional.objects.get_or_create(nombre='Prof', apellido='Test', defaults={'activo': True})
    profesional.sucursales.add(sucursal)
    profesional.servicios.add(servicio)
    paciente, _ = Paciente.objects.get_or_create(
        nombre='PacienteExcedente', apellido='Test',
        defaults={'estado': 'activo', 'fecha_nacimiento': date(2015, 1, 1), 'genero': 'M'}
    )
    paciente.sucursales.add(sucursal)
    metodo, _ = MetodoPago.objects.get_or_create(nombre='Efectivo')

    # Sesion de costo 100, pagada con un PAGO MASIVO de 150 (excedente de 50)
    sesion, _ = Sesion.objects.get_or_create(
        paciente=paciente, fecha=date(2060, 1, 1), hora_inicio=time(9, 0),
        defaults=dict(servicio=servicio, profesional=profesional, sucursal=sucursal,
                      hora_fin=time(9, 45), duracion_minutos=45, estado='realizada',
                      monto_cobrado=Decimal('100.00'), creada_por=user)
    )
    pago_masivo, _ = Pago.objects.get_or_create(
        numero_recibo='EXCEDENTE-TEST-0001', paciente=paciente,
        defaults=dict(fecha_pago=date.today(), monto=Decimal('150'), metodo_pago=metodo,
                      concepto='Pago masivo con excedente', registrado_por=user)
    )
    DetallePagoMasivo.objects.get_or_create(
        pago=pago_masivo, tipo='sesion', sesion=sesion,
        defaults=dict(monto=Decimal('150'), concepto='Detalle sesion con excedente via masivo')
    )

    client = Client()
    client.force_login(user)
    resp = client.get(f'/facturacion/api/cuenta/{paciente.id}/detalle/')
    print(f"status_code = {resp.status_code}")
    data = resp.json()
    excedentes = data['cuenta']['excedentes']
    print(f"excedentes = {excedentes} (esperado 50.0: pagó 150 por una sesión de 100)")
    assert resp.status_code == 200
    assert excedentes == 50.0, f"❌ El excedente por pago masivo no se detectó (dio {excedentes}, antes del fix hubiera dado 0.0)"
    print("✅ El excedente por pago masivo ahora se detecta correctamente")


if __name__ == '__main__':
    main()
