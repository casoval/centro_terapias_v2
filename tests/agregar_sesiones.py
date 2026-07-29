import os
import sys
from datetime import date, time, timedelta
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

cantidad_extra = int(sys.argv[1])

user = User.objects.get(username='test_perf')
sucursal = Sucursal.objects.get(nombre='Sucursal Test')
servicio = TipoServicio.objects.get(nombre='Servicio Test')
profesional = Profesional.objects.get(nombre='Prof', apellido='Test')
paciente = Paciente.objects.get(nombre='Paciente', apellido='Test')

existentes = Sesion.objects.filter(paciente=paciente).count()
hoy = date.today()

creadas = 0
for i in range(existentes, existentes + cantidad_extra):
    fecha = hoy - timedelta(days=i)
    try:
        Sesion.objects.create(
            paciente=paciente, fecha=fecha, hora_inicio=time(10, 0),
            servicio=servicio, profesional=profesional, sucursal=sucursal,
            hora_fin=time(10, 45), duracion_minutos=45,
            estado='realizada', monto_cobrado=Decimal('100.00'),
            creada_por=user,
        )
        creadas += 1
    except Exception as e:
        pass

print(f"Sesiones creadas en esta corrida: {creadas}")
print(f"Total sesiones ahora: {Sesion.objects.filter(paciente=paciente).count()}")
