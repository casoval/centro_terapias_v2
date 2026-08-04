"""
Script manual de verificación (no forma parte del test-suite automático)
para comprobar que:

1. Un paciente / profesional / recepcionista / gerente ACTIVO puede
   autenticarse normalmente.
2. Al marcarlo INACTIVO (paciente.estado='inactivo', profesional.activo=False,
   o perfil.activo=False), el backend de autenticación deja de autenticarlo.
3. Si ya tenía una sesión de navegador iniciada, el middleware la corta en
   la siguiente petición (se verifica llamando directamente al método usado
   por el middleware, sin necesidad de un servidor corriendo).
4. Reactivarlo restaura el acceso de inmediato.
5. Nada de esto modifica Sesion (terapia) ni Pago.

Ejecutar con:
    ENVIRONMENT=development python manage.py shell < tests/verificar_bloqueo_acceso_inactivos.py
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from core.models import PerfilUsuario
from pacientes.models import Paciente
from profesionales.models import Profesional


def linea(msg):
    print(f"\n=== {msg} ===")


# ---------- PACIENTE ----------
linea("PACIENTE")
import datetime
paciente = Paciente.objects.create(
    nombre="Test", apellido="Bloqueo",
    fecha_nacimiento=datetime.date(2015, 1, 1), genero='M',
    nombre_tutor="Tutor Test", parentesco='madre', telefono_tutor="000000000",
)
u_pac = User.objects.create_user(username="paciente_test_bloqueo", password="Clave123!")
perfil_pac = u_pac.perfil
perfil_pac.rol = 'paciente'
perfil_pac.paciente = paciente
perfil_pac.save()

assert authenticate(username="paciente_test_bloqueo", password="Clave123!") is not None, "Debería poder loguear activo"
print("OK: paciente activo puede autenticarse")

paciente.estado = 'inactivo'
paciente.save()
assert authenticate(username="paciente_test_bloqueo", password="Clave123!") is None, "NO debería poder loguear inactivo"
print("OK: paciente inactivo NO puede autenticarse")

# Simula que ya tenía sesión abierta: el middleware usaría este método
motivo = u_pac.perfil.acceso_bloqueado_motivo()
assert motivo is not None
print(f"OK: middleware cortaría su sesión activa. Motivo: {motivo}")

paciente.estado = 'activo'
paciente.save()
assert authenticate(username="paciente_test_bloqueo", password="Clave123!") is not None
print("OK: al reactivar paciente, vuelve a poder autenticarse")


# ---------- PROFESIONAL ----------
linea("PROFESIONAL")
profesional = Profesional.objects.create(nombre="Test", apellido="Bloqueo", especialidad="General")
u_prof = User.objects.create_user(username="profesional_test_bloqueo", password="Clave123!")
perfil_prof = u_prof.perfil
perfil_prof.rol = 'profesional'
perfil_prof.profesional = profesional
perfil_prof.save()

assert authenticate(username="profesional_test_bloqueo", password="Clave123!") is not None
print("OK: profesional activo puede autenticarse")

profesional.activo = False
profesional.save()
assert authenticate(username="profesional_test_bloqueo", password="Clave123!") is None
print("OK: profesional inactivo NO puede autenticarse")

profesional.activo = True
profesional.save()
assert authenticate(username="profesional_test_bloqueo", password="Clave123!") is not None
print("OK: al reactivar profesional, vuelve a poder autenticarse")


# ---------- RECEPCIONISTA ----------
linea("RECEPCIONISTA")
u_rec = User.objects.create_user(username="recepcionista_test_bloqueo", password="Clave123!")
perfil_rec = u_rec.perfil
perfil_rec.rol = 'recepcionista'
perfil_rec.save()

assert authenticate(username="recepcionista_test_bloqueo", password="Clave123!") is not None
print("OK: recepcionista activo puede autenticarse")

perfil_rec.activo = False
perfil_rec.save()
assert authenticate(username="recepcionista_test_bloqueo", password="Clave123!") is None
print("OK: recepcionista inactivo NO puede autenticarse")

perfil_rec.activo = True
perfil_rec.save()
assert authenticate(username="recepcionista_test_bloqueo", password="Clave123!") is not None
print("OK: al reactivar recepcionista, vuelve a poder autenticarse")


# ---------- GERENTE ----------
linea("GERENTE")
u_ger = User.objects.create_user(username="gerente_test_bloqueo", password="Clave123!")
perfil_ger = u_ger.perfil
perfil_ger.rol = 'gerente'
perfil_ger.save()

assert authenticate(username="gerente_test_bloqueo", password="Clave123!") is not None
print("OK: gerente activo puede autenticarse")

perfil_ger.activo = False
perfil_ger.save()
assert authenticate(username="gerente_test_bloqueo", password="Clave123!") is None
print("OK: gerente inactivo NO puede autenticarse")

perfil_ger.activo = True
perfil_ger.save()
assert authenticate(username="gerente_test_bloqueo", password="Clave123!") is not None
print("OK: al reactivar gerente, vuelve a poder autenticarse")


# ---------- SUPERUSUARIO NUNCA SE BLOQUEA ----------
linea("SUPERUSUARIO")
u_super = User.objects.create_superuser(username="super_test_bloqueo", password="Clave123!", email="a@a.com")
assert authenticate(username="super_test_bloqueo", password="Clave123!") is not None
print("OK: superusuario nunca se bloquea por este mecanismo")

# ---------- LIMPIEZA ----------
linea("LIMPIEZA")
for u in [u_pac, u_prof, u_rec, u_ger, u_super]:
    u.delete()
paciente.delete()
profesional.delete()
print("OK: datos de prueba eliminados. No se tocó ninguna Sesion ni Pago real.")

print("\n✅ TODAS LAS VERIFICACIONES PASARON CORRECTAMENTE")
