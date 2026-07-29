"""
Script de verificación manual de las optimizaciones aplicadas a agenda/.

No es un test formal (no usa TestCase) para poder imprimir el SQL generado
y los resultados de forma clara. Crea datos mínimos y ejercita:

  1. CalendarService.annotate_total_pagado()  -> total_pagado correcto
     (incluye pagos directos + pagos masivos) en UNA sola query.
  2. Sesion.total_pagado / .pagado             -> reutiliza el valor anotado
     (0 queries extra) cuando el queryset viene anotado.
  3. La vista calendario() completa, vía Django test Client, para asegurarnos
     de que no quedó ningún error de referencia/campo.
"""
import os
import sys
import django

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection, reset_queries
from django.test import Client
from django.conf import settings

settings.DEBUG = True  # para poder contar queries con connection.queries

from servicios.models import Sucursal, TipoServicio
from profesionales.models import Profesional
from pacientes.models import Paciente
from agenda.models import Sesion
from agenda.services import CalendarService
from facturacion.models import Pago, MetodoPago, DetallePagoMasivo


def get_or_create_minimo():
    user, _ = User.objects.get_or_create(username='test_perf', defaults={'is_superuser': True, 'is_staff': True})
    user.set_password('test12345')
    user.is_superuser = True
    user.save()

    sucursal, _ = Sucursal.objects.get_or_create(nombre='Sucursal Test', defaults={'activa': True, 'direccion': 'Calle Falsa 123'})

    servicio, _ = TipoServicio.objects.get_or_create(
        nombre='Servicio Test',
        defaults={'activo': True, 'color': '#3498db', 'duracion_minutos': 45, 'costo_base': Decimal('100.00')}
    )

    profesional, _ = Profesional.objects.get_or_create(
        nombre='Prof', apellido='Test', defaults={'activo': True}
    )
    profesional.sucursales.add(sucursal)
    profesional.servicios.add(servicio)

    paciente, _ = Paciente.objects.get_or_create(
        nombre='Paciente', apellido='Test',
        defaults={'estado': 'activo', 'fecha_nacimiento': date(2015, 1, 1), 'genero': 'M'}
    )
    paciente.sucursales.add(sucursal)

    metodo, _ = MetodoPago.objects.get_or_create(nombre='Efectivo')

    return user, sucursal, servicio, profesional, paciente, metodo


def crear_sesiones(paciente, servicio, profesional, sucursal, user, cantidad=30):
    hoy = date.today()
    creadas = []
    for i in range(cantidad):
        fecha = hoy - timedelta(days=i)
        s, created = Sesion.objects.get_or_create(
            paciente=paciente, fecha=fecha, hora_inicio=time(10, 0),
            defaults=dict(
                servicio=servicio, profesional=profesional, sucursal=sucursal,
                hora_fin=time(10, 45), duracion_minutos=45,
                estado='realizada', monto_cobrado=Decimal('100.00'),
                creada_por=user,
            )
        )
        creadas.append(s)
    return creadas


def main():
    import sys
    cantidad = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    print(f"=== Preparando datos mínimos de prueba ({cantidad} sesiones) ===")
    user, sucursal, servicio, profesional, paciente, metodo = get_or_create_minimo()
    sesiones = crear_sesiones(paciente, servicio, profesional, sucursal, user, cantidad=cantidad)

    # Pago directo de una sesión (completo)
    s_pagada = sesiones[0]
    Pago.objects.get_or_create(
        numero_recibo='TESTPERF-0001', paciente=paciente, sesion=s_pagada,
        defaults=dict(fecha_pago=date.today(), monto=Decimal('100'), metodo_pago=metodo,
                      concepto='Pago directo test', registrado_por=user)
    )

    # Pago MASIVO que cubre otra sesión (esto es lo que antes NO se sumaba
    # correctamente en las estadísticas del calendario)
    s_pago_masivo = sesiones[1]
    pago_masivo, _ = Pago.objects.get_or_create(
        numero_recibo='TESTPERF-0002', paciente=paciente,
        defaults=dict(fecha_pago=date.today(), monto=Decimal('100'), metodo_pago=metodo,
                      concepto='Pago masivo test', registrado_por=user)
    )
    DetallePagoMasivo.objects.get_or_create(
        pago=pago_masivo, tipo='sesion', sesion=s_pago_masivo,
        defaults=dict(monto=Decimal('100'), concepto='Detalle sesion via pago masivo')
    )

    print(f"Sesiones creadas/existentes: {len(sesiones)}")

    print("\n=== 1) Verificando CalendarService.annotate_total_pagado ===")
    qs = CalendarService.annotate_total_pagado(Sesion.objects.filter(paciente=paciente))
    resultados = {s.id: s.total_pagado_sesion for s in qs}
    print(f"  Sesión con pago DIRECTO   (id={s_pagada.id}): total_pagado_sesion = {resultados.get(s_pagada.id)} (esperado 100)")
    print(f"  Sesión con pago MASIVO    (id={s_pago_masivo.id}): total_pagado_sesion = {resultados.get(s_pago_masivo.id)} (esperado 100)")
    otras = [v for k, v in resultados.items() if k not in (s_pagada.id, s_pago_masivo.id)]
    print(f"  Resto de sesiones sin pago: valores = {set(otras)} (esperado {{Decimal('0.00')}} o similar)")

    assert resultados.get(s_pagada.id) == Decimal('100'), "❌ Falló el cálculo de pago directo"
    assert resultados.get(s_pago_masivo.id) == Decimal('100'), "❌ Falló el cálculo de pago MASIVO (bug que corregimos)"
    print("  ✅ Los montos anotados son correctos (incluyendo pago masivo)")

    print("\n=== 2) Verificando que Sesion.pagado NO dispare queries extra cuando está anotado ===")
    sesion_anotada = qs.get(id=s_pagada.id)
    reset_queries()
    valor_pagado = sesion_anotada.pagado
    n_queries = len(connection.queries)
    print(f"  sesion.pagado = {valor_pagado} -> queries SQL disparadas: {n_queries} (esperado 0)")
    assert n_queries == 0, "❌ sesion.pagado sigue lanzando queries incluso estando anotado"
    print("  ✅ 0 queries extra, se reutilizó la anotación")

    print("\n=== 3) Verificando fallback (sin anotar) sigue funcionando igual que antes ===")
    sesion_sin_anotar = Sesion.objects.get(id=s_pagada.id)
    reset_queries()
    valor_fallback = sesion_sin_anotar.pagado
    n_queries_fallback = len(connection.queries)
    print(f"  sesion.pagado (sin anotar) = {valor_fallback} -> queries: {n_queries_fallback} (esperado 2: pagos directos + masivos)")
    assert valor_fallback == valor_pagado, "❌ El fallback da un resultado distinto al anotado"
    print("  ✅ El fallback sigue funcionando igual que antes de la optimización")

    print("\n=== 4) Ejercitando la vista /agenda/ completa (vista LISTA, SIN filtro de fecha, la más pesada) ===")
    import time as time_mod
    client = Client()
    client.force_login(user)
    reset_queries()
    t0 = time_mod.perf_counter()
    resp = client.get('/agenda/', {'vista': 'lista', 'por_pagina': '25'})
    elapsed = time_mod.perf_counter() - t0
    n_queries_vista = len(connection.queries)
    total_sesiones_bd = Sesion.objects.count()
    print(f"  Total de sesiones en la BD (histórico completo): {total_sesiones_bd}")
    print(f"  status_code = {resp.status_code}")
    print(f"  queries SQL totales para renderizar la página 1 (25 filas): {n_queries_vista}")
    print(f"  tiempo de la vista (sin contar arranque de Django): {elapsed*1000:.1f} ms")
    assert resp.status_code == 200, f"❌ La vista falló: {resp.status_code}"
    print("  ✅ La vista responde 200 OK con la nueva lógica de paginación + anotaciones")

    print("\n=== 5) Vista mensual (rango acotado) ===")
    reset_queries()
    resp2 = client.get('/agenda/', {'vista': 'mensual'})
    n_queries_mensual = len(connection.queries)
    print(f"  status_code = {resp2.status_code}, queries SQL: {n_queries_mensual}")
    assert resp2.status_code == 200

    print("\n🎉 TODAS LAS VERIFICACIONES PASARON")


if __name__ == '__main__':
    main()
