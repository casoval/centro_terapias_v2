"""
Pruebas del módulo "Permisos de Edición" y de los controles de acceso
asociados (cambio de estado con pagos y foto del paciente por el profesional).

Ejecutar:  python manage.py test agenda.test_permisos_edicion
"""
import io
from datetime import date, time, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from agenda.forms import PermisoEdicionForm
from agenda.models import PermisoEdicionSesion, Sesion
from pacientes.models import Paciente
from profesionales.models import Profesional
from servicios.models import Sucursal, TipoServicio


def _usuario(username, rol, **extra):
    u = User.objects.create_user(username, f'{username}@x.com', 'pass1234', **extra)
    u.perfil.rol = rol
    u.perfil.save()
    return u


class BaseCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.suc = Sucursal.objects.create(nombre='Central', direccion='Calle 1')
        cls.serv = TipoServicio.objects.create(nombre='Lenguaje', costo_base=100)
        cls.admin = User.objects.create_superuser('admin', 'a@x.com', 'pass1234')
        cls.recep = _usuario('recep', 'recepcionista')
        cls.recep.perfil.sucursales.add(cls.suc)

        cls.u_prof = _usuario('prof', 'profesional')
        cls.u_prof2 = _usuario('prof2', 'profesional')
        cls.prof = Profesional.objects.create(
            user=cls.u_prof, nombre='Ana', apellido='Gomez', especialidad='Lenguaje')
        cls.prof2 = Profesional.objects.create(
            user=cls.u_prof2, nombre='Luis', apellido='Perez', especialidad='Lenguaje')

        cls.pac = Paciente.objects.create(
            nombre='Nico', apellido='Mendoza', fecha_nacimiento=date(2020, 1, 1),
            genero='M', nombre_tutor='Mama', parentesco='madre', telefono_tutor='7')
        cls.pac.sucursales.add(cls.suc)

        cls.pasada = date.today() - timedelta(days=3)

    def sesion(self, prof=None, fecha=None, estado='programada', notas='orig'):
        s = Sesion(
            paciente=self.pac, servicio=self.serv, profesional=prof or self.prof,
            sucursal=self.suc, fecha=fecha or self.pasada, hora_inicio=time(9, 0),
            hora_fin=time(10, 0), duracion_minutos=60, estado=estado,
            notas_sesion=notas, creada_por=self.admin)
        Sesion.objects.bulk_create([s])  # evita validaciones de choque de horario
        return Sesion.objects.latest('id')

    def permiso(self, prof=None, estado=True, notas=True, otros=False,
                desde=None, hasta=None, horas=2):
        ahora = timezone.now()
        return PermisoEdicionSesion.objects.create(
            profesional=prof or self.prof,
            fecha_sesion_desde=desde or self.pasada - timedelta(days=5),
            fecha_sesion_hasta=hasta or self.pasada + timedelta(days=1),
            valido_desde=ahora - timedelta(hours=1),
            valido_hasta=ahora + timedelta(hours=horas),
            puede_editar_estado=estado, puede_editar_notas=notas,
            puede_editar_otros_campos=otros, otorgado_por=self.admin)

    def editar(self, user, sesion, estado, notas):
        self.client.force_login(user)
        return self.client.post(
            reverse('agenda:editar_sesion', args=[sesion.id]),
            {'estado': estado, 'notas_sesion': notas})


class PermisoEdicionTests(BaseCase):

    def test_sin_permiso_sesion_pasada_bloqueada(self):
        s = self.sesion()
        r = self.editar(self.u_prof, s, 'realizada', 'x')
        self.assertEqual(r.status_code, 403)
        s.refresh_from_db()
        self.assertEqual((s.estado, s.notas_sesion), ('programada', 'orig'))

    def test_permiso_completo_permite_estado_y_notas(self):
        s = self.sesion()
        self.permiso()
        r = self.editar(self.u_prof, s, 'realizada', 'nueva')
        self.assertEqual(r.status_code, 200, r.content)
        s.refresh_from_db()
        self.assertEqual((s.estado, s.notas_sesion), ('realizada', 'nueva'))

    def test_permiso_solo_notas_no_cambia_el_estado(self):
        s = self.sesion()
        self.permiso(estado=False, notas=True)
        r = self.editar(self.u_prof, s, 'realizada', 'solo notas')
        self.assertEqual(r.status_code, 200, r.content)
        s.refresh_from_db()
        self.assertEqual(s.estado, 'programada')          # NO cambió
        self.assertEqual(s.notas_sesion, 'solo notas')    # sí cambió

    def test_permiso_solo_estado_no_cambia_las_notas(self):
        s = self.sesion()
        self.permiso(estado=True, notas=False)
        r = self.editar(self.u_prof, s, 'falta', 'intento')
        self.assertEqual(r.status_code, 200, r.content)
        s.refresh_from_db()
        self.assertEqual(s.estado, 'falta')               # sí cambió
        self.assertEqual(s.notas_sesion, 'orig')          # NO cambió

    def test_permiso_no_aplica_a_sesiones_de_otro_profesional(self):
        s_ajena = self.sesion(prof=self.prof2)
        self.permiso(prof=self.prof)                      # permiso de Ana
        r = self.editar(self.u_prof, s_ajena, 'realizada', 'x')
        self.assertEqual(r.status_code, 403)
        s_ajena.refresh_from_db()
        self.assertEqual(s_ajena.estado, 'programada')

    def test_permiso_vencido_no_sirve(self):
        s = self.sesion()
        p = self.permiso()
        p.valido_hasta = timezone.now() - timedelta(minutes=1)
        p.save()
        self.assertEqual(self.editar(self.u_prof, s, 'realizada', 'x').status_code, 403)

    def test_permiso_fuera_del_rango_de_fechas_no_sirve(self):
        s = self.sesion(fecha=self.pasada - timedelta(days=30))
        self.permiso()
        self.assertEqual(self.editar(self.u_prof, s, 'realizada', 'x').status_code, 403)

    def test_varios_permisos_suman_sus_campos(self):
        s = self.sesion()
        self.permiso(estado=True, notas=False)
        self.permiso(estado=False, notas=True)
        r = self.editar(self.u_prof, s, 'realizada', 'ambos')
        self.assertEqual(r.status_code, 200, r.content)
        s.refresh_from_db()
        self.assertEqual((s.estado, s.notas_sesion), ('realizada', 'ambos'))

    def test_uso_se_registra_solo_si_guardo_bien(self):
        s = self.sesion()
        p = self.permiso()
        r = self.editar(self.u_prof, s, 'estado_que_no_existe', 'x')
        self.assertEqual(r.status_code, 400)
        p.refresh_from_db()
        self.assertIsNone(p.fecha_uso)                    # intento fallido: no cuenta
        r = self.editar(self.u_prof, s, 'realizada', 'ok')
        self.assertEqual(r.status_code, 200)
        p.refresh_from_db()
        self.assertIsNotNone(p.fecha_uso)                 # guardado ok: se registra

    def test_sesion_de_hoy_siempre_editable_por_su_profesional(self):
        s = self.sesion(fecha=date.today())
        self.assertEqual(self.editar(self.u_prof, s, 'realizada', 'hoy').status_code, 200)

    # ── formulario ──
    def _datos_form(self, **kw):
        ahora = timezone.localtime(timezone.now())
        d = {
            'profesional': self.prof.id,
            'fecha_sesion_desde': (date.today() - timedelta(days=5)).isoformat(),
            'fecha_sesion_hasta': date.today().isoformat(),
            'valido_desde': (ahora - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'),
            'valido_hasta': (ahora + timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M'),
            'puede_editar_estado': 'on', 'puede_editar_notas': 'on', 'motivo': 'x',
        }
        d.update(kw)
        return d

    def test_form_acepta_permiso_vigente(self):
        self.assertTrue(PermisoEdicionForm(self._datos_form()).is_valid())

    def test_form_rechaza_permiso_ya_vencido(self):
        ahora = timezone.localtime(timezone.now())
        f = PermisoEdicionForm(self._datos_form(
            valido_desde=(ahora - timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M'),
            valido_hasta=(ahora - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M')))
        self.assertFalse(f.is_valid())

    def test_form_rechaza_rangos_invertidos(self):
        f = PermisoEdicionForm(self._datos_form(
            fecha_sesion_desde=date.today().isoformat(),
            fecha_sesion_hasta=(date.today() - timedelta(days=2)).isoformat()))
        self.assertFalse(f.is_valid())

    # ── pantallas de administración ──
    def test_lista_solo_para_staff(self):
        self.client.force_login(self.u_prof)
        r = self.client.get(reverse('agenda:lista_permisos_edicion'))
        self.assertEqual(r.status_code, 302)              # no entra
        self.client.force_login(self.admin)
        r = self.client.get(reverse('agenda:lista_permisos_edicion'))
        self.assertEqual(r.status_code, 200)

    def test_admin_crea_y_revoca_permiso(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse('agenda:crear_permiso_edicion'), self._datos_form())
        self.assertEqual(r.status_code, 302)
        p = PermisoEdicionSesion.objects.get()
        self.assertTrue(p.esta_activo)
        self.assertEqual(p.otorgado_por, self.admin)
        self.client.post(reverse('agenda:revocar_permiso_edicion', args=[p.id]))
        self.assertFalse(PermisoEdicionSesion.objects.exists())

    def test_contador_del_calendario_ignora_permisos_vencidos_hoy(self):
        # vence hace 1 minuto, el mismo día: ya NO debe contar como activo
        p = self.permiso()
        p.valido_desde = timezone.now() - timedelta(days=2)
        p.valido_hasta = timezone.now() - timedelta(minutes=1)
        p.save()
        self.client.force_login(self.admin)
        r = self.client.get(reverse('agenda:calendario'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['permisos_activos_count'], 0)


class AccesoPagosTests(BaseCase):
    """procesar_cambio_estado / modal: solo admin, gerente y recepción."""

    def test_profesional_no_puede_procesar_cambio_de_estado(self):
        s = self.sesion()
        self.client.force_login(self.u_prof)
        r = self.client.post(reverse('agenda:procesar_cambio_estado', args=[s.id]),
                             {'estado_nuevo': 'cancelada', 'accion_pago': 'anular_pago',
                              'motivo_anulacion': 'x'})
        self.assertEqual(r.status_code, 403)
        s.refresh_from_db()
        self.assertEqual(s.estado, 'programada')

    def test_profesional_no_ve_el_modal_de_pagos(self):
        s = self.sesion()
        self.client.force_login(self.u_prof)
        r = self.client.get(reverse('agenda:modal_confirmar_estado', args=[s.id]),
                            {'estado_nuevo': 'permiso'})
        self.assertEqual(r.status_code, 403)

    def test_recepcion_pasa_el_control_de_rol(self):
        s = self.sesion()
        self.client.force_login(self.recep)
        r = self.client.post(reverse('agenda:procesar_cambio_estado', args=[s.id]),
                             {'estado_nuevo': 'cancelada'})   # falta accion_pago
        self.assertEqual(r.status_code, 400)                  # validó, no fue 403


class MensajePermisoPacienteTests(BaseCase):
    def test_mis_sesiones_ya_no_promete_reprogramar(self):
        u_pac = _usuario('familia', 'paciente')
        u_pac.perfil.paciente = self.pac
        u_pac.perfil.save()
        self.sesion(estado='permiso', notas='')
        self.client.force_login(u_pac)
        r = self.client.get(reverse('pacientes:mis_sesiones'))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertNotIn('se puede reprogramar', html)
        self.assertNotIn('autorizada como permiso', html)


def _png():
    from PIL import Image
    b = io.BytesIO()
    Image.new('RGB', (10, 10), 'red').save(b, 'PNG')
    return SimpleUploadedFile('f.png', b.getvalue(), content_type='image/png')


class FotoProfesionalTests(BaseCase):
    def url(self):
        return reverse('profesionales:subir_foto_paciente', args=[self.pac.id])

    def test_sube_si_no_tiene_foto(self):
        self.sesion()
        self.client.force_login(self.u_prof)
        with mock.patch.object(Paciente, 'save') as guardar:
            r = self.client.post(self.url(), {'foto': _png()})
        self.assertEqual(r.status_code, 302)
        guardar.assert_called_once_with(update_fields=['foto'])

    def test_no_sube_si_ya_tiene_foto(self):
        self.sesion()
        Paciente.objects.filter(pk=self.pac.pk).update(foto='pacientes/ya_tiene')
        self.client.force_login(self.u_prof)
        with mock.patch.object(Paciente, 'save') as guardar:
            self.client.post(self.url(), {'foto': _png()})
        guardar.assert_not_called()

    def test_no_sube_si_no_es_su_paciente(self):
        self.sesion(prof=self.prof2)                       # el paciente es de otra
        self.client.force_login(self.u_prof)
        with mock.patch.object(Paciente, 'save') as guardar:
            self.client.post(self.url(), {'foto': _png()})
        guardar.assert_not_called()

    def test_rechaza_archivos_que_no_son_imagen(self):
        self.sesion()
        self.client.force_login(self.u_prof)
        falso = SimpleUploadedFile('f.png', b'no soy imagen', content_type='image/png')
        with mock.patch.object(Paciente, 'save') as guardar:
            self.client.post(self.url(), {'foto': falso})
        guardar.assert_not_called()

    def test_get_no_sube_nada(self):
        self.client.force_login(self.u_prof)
        self.assertEqual(self.client.get(self.url()).status_code, 302)

    def test_recepcion_no_usa_esta_ruta(self):
        self.client.force_login(self.recep)
        with mock.patch.object(Paciente, 'save') as guardar:
            self.client.post(self.url(), {'foto': _png()})
        guardar.assert_not_called()


class AccesoPacientesPorRolTests(BaseCase):
    def test_profesional_no_puede_editar_ni_eliminar_pacientes(self):
        self.client.force_login(self.u_prof)
        for nombre in ('editar', 'eliminar'):
            r = self.client.get(reverse(f'pacientes:{nombre}', args=[self.pac.id]))
            self.assertEqual(r.status_code, 302)
            self.assertIn('dashboard', r.url)
        self.assertEqual(self.client.get(reverse('pacientes:agregar')).status_code, 302)

    def test_recepcion_y_admin_siguen_editando(self):
        for u in (self.recep, self.admin):
            self.client.force_login(u)
            r = self.client.get(reverse('pacientes:editar', args=[self.pac.id]))
            self.assertEqual(r.status_code, 200, u.username)

    def test_profesional_solo_ve_ficha_de_sus_pacientes(self):
        self.client.force_login(self.u_prof)
        self.assertEqual(self.client.get(reverse('pacientes:detalle', args=[self.pac.id])).status_code, 302)
        self.sesion()
        self.assertEqual(self.client.get(reverse('pacientes:detalle', args=[self.pac.id])).status_code, 200)
