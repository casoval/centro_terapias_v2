from datetime import date, time, timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from agenda.models import Sesion
from core.models import PerfilUsuario
from pacientes.models import Paciente
from profesionales.models import Profesional
from servicios.models import Sucursal, TipoServicio

from . import alertas, visibilidad
from .models import Anuncio, AnuncioLectura

User = get_user_model()


def hoy():
    return timezone.localdate()


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.s1 = Sucursal.objects.create(nombre='Japón', direccion='x')
        cls.s2 = Sucursal.objects.create(nombre='Camacho', direccion='y')
        cls.servicio = TipoServicio.objects.create(nombre='Terapia', costo_base=Decimal('100'))
        cls.admin = User.objects.create_superuser('admin', 'a@a.com', 'x')
        cls.gerente = cls._staff('gerente', 'gerente', [cls.s1, cls.s2])
        cls.rec1 = cls._staff('rec1', 'recepcionista', [cls.s1])
        cls.rec2 = cls._staff('rec2', 'recepcionista', [cls.s2])
        cls.prof_obj = Profesional.objects.create(nombre='Ana', apellido='Prof', especialidad='x')
        cls.prof_obj.sucursales.add(cls.s1)
        cls.prof_obj.servicios.add(cls.servicio)
        cls.prof = User.objects.create_user('prof', password='x')
        PerfilUsuario.objects.update_or_create(user=cls.prof, defaults={'rol': 'profesional', 'profesional': cls.prof_obj})
        cls.prof = User.objects.get(pk=cls.prof.pk)
        cls.prof2_obj = Profesional.objects.create(nombre='Beto', apellido='Otro', especialidad='x')
        cls.prof2_obj.sucursales.add(cls.s2)
        cls.prof2_obj.servicios.add(cls.servicio)
        cls.pac1 = cls._paciente('Luis', [cls.s1])
        cls.pac2 = cls._paciente('Eva', [cls.s2])
        cls.user_pac = User.objects.create_user('pac', password='x')
        PerfilUsuario.objects.update_or_create(user=cls.user_pac, defaults={'rol': 'paciente', 'paciente': cls.pac1})
        cls.user_pac = User.objects.get(pk=cls.user_pac.pk)

    @classmethod
    def _staff(cls, nombre, rol, sucs):
        u = User.objects.create_user(nombre, password='x')
        p, _ = PerfilUsuario.objects.update_or_create(user=u, defaults={'rol': rol})
        p.sucursales.set(sucs)
        return User.objects.get(pk=u.pk)   # sin perfil cacheado por la señal

    @classmethod
    def _paciente(cls, nombre, sucs, estado='activo'):
        p = Paciente.objects.create(nombre=nombre, apellido='Test', fecha_nacimiento=date(2018, 1, 1), genero='M',
                                    nombre_tutor='T', parentesco='madre', telefono_tutor='70000000', estado=estado)
        p.sucursales.set(sucs)
        return p

    def sesion(self, pac, dias, estado, prof=None, suc=None):
        return Sesion.objects.create(
            paciente=pac, fecha=hoy() - timedelta(days=dias), hora_inicio=time(10, 0), hora_fin=time(10, 45),
            duracion_minutos=45, servicio=self.servicio, profesional=prof or self.prof_obj,
            sucursal=suc or self.s1, estado=estado, monto_cobrado=Decimal('100'), creada_por=self.admin)

    def anuncio(self, **kw):
        d = dict(titulo='Aviso', mensaje='hola', fecha_inicio=hoy(), fecha_fin=hoy(), dest_pacientes=True)
        d.update(kw)
        suc = d.pop('suc', None)
        a = Anuncio.objects.create(**d)
        if suc:
            a.sucursales.set(suc)
        return a


class VisibilidadTests(Base):
    def test_vigencia_inclusiva(self):
        ayer = self.anuncio(titulo='fin ayer', fecha_inicio=hoy() - timedelta(days=3), fecha_fin=hoy() - timedelta(days=1))
        hoy_ = self.anuncio(titulo='hoy', fecha_fin=hoy())
        manana = self.anuncio(titulo='mañana', fecha_inicio=hoy() + timedelta(days=1), fecha_fin=hoy() + timedelta(days=2))
        ids = set(visibilidad.anuncios_vigentes(self.user_pac).values_list('id', flat=True))
        self.assertEqual(ids, {hoy_.id})
        self.assertNotIn(ayer.id, ids)
        self.assertNotIn(manana.id, ids)

    def test_audiencia_por_rol(self):
        a = self.anuncio(dest_pacientes=False, dest_profesionales=True)
        self.assertEqual(visibilidad.anuncios_vigentes(self.prof).count(), 1)
        self.assertEqual(visibilidad.anuncios_vigentes(self.user_pac).count(), 0)
        self.assertEqual(visibilidad.anuncios_vigentes(self.rec1).count(), 0)
        self.assertEqual(visibilidad.anuncios_vigentes(self.admin).count(), 1)   # el admin ve todos

    def test_filtro_sucursal(self):
        self.anuncio(dest_recepcionistas=True, dest_pacientes=False, suc=[self.s2])
        self.assertEqual(visibilidad.anuncios_vigentes(self.rec1).count(), 0)
        self.assertEqual(visibilidad.anuncios_vigentes(self.rec2).count(), 1)

    def test_urgentes_primero(self):
        self.anuncio(titulo='normal')
        u = self.anuncio(titulo='urgente', importancia='urgente')
        self.assertEqual(visibilidad.anuncios_vigentes(self.user_pac).first().id, u.id)

    def test_historial_solo_si_se_guarda(self):
        fin = hoy() - timedelta(days=1)
        si = self.anuncio(fecha_inicio=fin, fecha_fin=fin, guardar_en_historial=True)
        no = self.anuncio(fecha_inicio=fin, fecha_fin=fin, guardar_en_historial=False)
        ids = set(visibilidad.anuncios_historial(self.user_pac).values_list('id', flat=True))
        self.assertEqual(ids, {si.id})
        self.assertNotIn(no.id, ids)

    def test_comando_limpia_solo_los_no_guardados(self):
        fin = hoy() - timedelta(days=1)
        self.anuncio(fecha_inicio=fin, fecha_fin=fin, guardar_en_historial=False)
        keep = self.anuncio(fecha_inicio=fin, fecha_fin=fin, guardar_en_historial=True)
        vivo = self.anuncio(guardar_en_historial=False)
        call_command('limpiar_anuncios', stdout=StringIO())
        self.assertEqual(set(Anuncio.objects.values_list('id', flat=True)), {keep.id, vivo.id})

    def test_usuarios_destino_con_sucursal(self):
        a = self.anuncio(dest_recepcionistas=True, dest_pacientes=True, suc=[self.s1])
        nombres = set(visibilidad.usuarios_destino(a).values_list('username', flat=True))
        self.assertEqual(nombres, {'rec1', 'pac'})


class AlertasTests(Base):
    def claves(self, user):
        return {a['clave']: a for a in alertas.alertas_para(user)}

    def test_faltas_seguidas_y_permiso_corta_racha(self):
        for d in (5, 4, 3):
            self.sesion(self.pac1, d, 'falta')
        a = self.claves(self.admin)['faltas']
        self.assertEqual(a['nivel'], 'urgente')
        # un permiso reciente corta la racha
        self.sesion(self.pac1, 1, 'permiso')
        self.assertNotIn('faltas', self.claves(self.admin))

    def test_dos_faltas_es_atencion_y_cancelada_se_ignora(self):
        self.sesion(self.pac1, 6, 'falta')
        self.sesion(self.pac1, 3, 'cancelada')
        self.sesion(self.pac1, 2, 'falta')
        self.assertEqual(self.claves(self.admin)['faltas']['nivel'], 'atencion')

    def test_realizada_corta_racha(self):
        self.sesion(self.pac1, 6, 'falta')
        self.sesion(self.pac1, 5, 'falta')
        self.sesion(self.pac1, 1, 'realizada')
        self.assertNotIn('faltas', self.claves(self.admin))

    def test_faltas_alcance_por_sucursal_y_profesional(self):
        for d in (4, 3):
            self.sesion(self.pac2, d, 'falta', suc=self.s2, prof=self.prof2_obj)
        self.assertIn('faltas', self.claves(self.rec2))
        self.assertNotIn('faltas', self.claves(self.rec1))
        self.assertNotIn('faltas', self.claves(self.prof))   # pac2 no es paciente de este profesional
        for d in (4, 3):
            self.sesion(self.pac1, d, 'falta')
        self.assertIn('faltas', self.claves(self.prof))

    def test_paciente_inactivo_no_alerta(self):
        inactivo = self._paciente('Inac', [self.s1], estado='inactivo')
        for d in (4, 3, 2):
            self.sesion(inactivo, d, 'falta')
        self.assertNotIn('faltas', self.claves(self.admin))

    def test_sesiones_sin_estado(self):
        self.sesion(self.pac1, 3, 'programada')
        self.assertIn('sin_estado', self.claves(self.admin))
        self.assertIn('sin_estado', self.claves(self.rec1))
        self.assertNotIn('sin_estado', self.claves(self.rec2))
        self.assertIn('sin_estado', self.claves(self.prof))
        self.assertNotIn('sin_estado', self.claves(self.user_pac))

    def test_abandono(self):
        self.sesion(self.pac1, 30, 'realizada')
        self.sesion(self.pac1, -2, 'programada')
        self.assertIn('abandono', self.claves(self.admin))

    def test_transferencias_y_respaldo_solo_admin(self):
        with override_settings(AVISOS_CHEQUEAR_RESPALDOS=True):
            self.assertIn('respaldo_viejo', self.claves(self.admin))
            self.assertNotIn('respaldo_viejo', self.claves(self.gerente))

    def test_saldo_paciente(self):
        from facturacion.models import CuentaCorriente
        cc, _ = CuentaCorriente.objects.get_or_create(paciente=self.pac1)
        self.sesion(self.pac1, 45, 'realizada')
        CuentaCorriente.objects.filter(pk=cc.pk).update(saldo_actual=Decimal('-100'), saldo_real=Decimal('-100'))
        a = self.claves(self.user_pac)['saldo']
        self.assertIn('Tienes un saldo pendiente de Bs. 100.00', a['detalle'])
        # deuda reciente (<30 días) no avisa
        Sesion.objects.all().delete()
        self.sesion(self.pac1, 5, 'realizada')
        self.assertNotIn('saldo', self.claves(self.user_pac))

    def test_deuda_solo_activos_y_umbrales(self):
        from facturacion.models import CuentaCorriente
        for pac, dias in ((self.pac1, 70), (self._paciente('Inac', [self.s1], 'inactivo'), 90)):
            self.sesion(pac, dias, 'realizada')
            cc, _ = CuentaCorriente.objects.get_or_create(paciente=pac)
            CuentaCorriente.objects.filter(pk=cc.pk).update(saldo_actual=Decimal('-100'), saldo_real=Decimal('-100'))
        a = self.claves(self.admin)['deuda']
        self.assertEqual(a['nivel'], 'urgente')
        self.assertIn('1 paciente activo', a['detalle'])      # el inactivo no cuenta
        self.assertIn('deuda', self.claves(self.rec1))
        self.assertNotIn('deuda', self.claves(self.rec2))
        self.assertNotIn('deuda', self.claves(self.prof))

    def test_urls_de_alertas_existen(self):
        for n in ('recordatorios:bots-monitor', 'facturacion:cuentas_corrientes', 'pacientes:lista',
                  'profesionales:mis_pacientes', 'agenda:calendario', 'inventario:transferencias',
                  'recordatorios:backup_monitor', 'facturacion:mis_deudas'):
            reverse(n)

    def test_bots_por_sucursal(self):
        with override_settings(AVISOS_CHEQUEAR_BOTS=True):
            from django.core.cache import cache
            cache.clear()
            a = {x['clave'] for x in alertas.alertas_para(self.admin)}
            self.assertTrue({'bot_japon', 'bot_camacho'} <= a)           # sin bot corriendo → desconectado
            r = {x['clave'] for x in alertas.alertas_para(self.rec1)}
            self.assertEqual({k for k in r if k.startswith('bot_')} & {'bot_camacho'}, set())
        self.assertFalse([x for x in alertas.alertas_para(self.admin) if x['clave'].startswith('bot_')])


class VistasTests(Base):
    def test_popup_cada_vez_para_admin_gerente_recepcion(self):
        self.anuncio(dest_recepcionistas=True, dest_pacientes=False)
        self.client.force_login(self.rec1)
        for _ in range(3):
            r = self.client.get(reverse('avisos:popup_data')).json()
            self.assertTrue(r['mostrar'])
            self.assertEqual(len(r['anuncios']), 1)

    def test_popup_una_vez_por_login_para_profesional_y_paciente(self):
        self.anuncio(dest_pacientes=True, dest_profesionales=True)
        for u in (self.user_pac, self.prof):
            self.client.force_login(u)
            self.assertTrue(self.client.get(reverse('avisos:popup_data')).json()['mostrar'], u.username)
            # recargas (filtros, vistas) no lo vuelven a mostrar
            for _ in range(3):
                r = self.client.get(reverse('avisos:popup_data')).json()
                self.assertFalse(r['mostrar'])
                self.assertEqual(r['total'], 1)
            # algo nuevo → vuelve a salir una vez
            self.anuncio(titulo='Nuevo', dest_pacientes=True, dest_profesionales=True)
            self.assertTrue(self.client.get(reverse('avisos:popup_data')).json()['mostrar'])
            self.assertFalse(self.client.get(reverse('avisos:popup_data')).json()['mostrar'])
            Anuncio.objects.filter(titulo='Nuevo').delete()
        # al día siguiente, aunque no haya cerrado sesión → vuelve a salir (una vez)
        from unittest import mock
        manana = hoy() + timedelta(days=1)
        self.anuncio(titulo='Largo', dest_profesionales=True, fecha_fin=manana)
        self.client.force_login(self.prof)
        self.assertTrue(self.client.get(reverse('avisos:popup_data')).json()['mostrar'])
        self.assertFalse(self.client.get(reverse('avisos:popup_data')).json()['mostrar'])   # mismo día
        with mock.patch('avisos.views.timezone.localdate', return_value=manana), \
                mock.patch('avisos.visibilidad.timezone.localdate', return_value=manana):
            self.assertTrue(self.client.get(reverse('avisos:popup_data')).json()['mostrar'])
            self.assertFalse(self.client.get(reverse('avisos:popup_data')).json()['mostrar'])
        # nuevo inicio de sesión → vuelve a salir
        self.client.logout()
        self.client.force_login(self.prof)
        self.assertTrue(self.client.get(reverse('avisos:popup_data')).json()['mostrar'])

    def test_popup_vacio_no_abre(self):
        self.client.force_login(self.user_pac)
        r = self.client.get(reverse('avisos:popup_data')).json()
        self.assertEqual(r['total'], 0)
        self.assertFalse(r['mostrar'])

    def test_solo_admin_gestiona(self):
        a = self.anuncio()
        for u in (self.gerente, self.rec1, self.prof, self.user_pac):
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse('avisos:crear')).status_code, 302)
            self.assertEqual(self.client.post(reverse('avisos:eliminar', args=[a.pk])).status_code, 302)
            self.assertEqual(self.client.get(reverse('avisos:lecturas', args=[a.pk])).status_code, 302)
        self.assertTrue(Anuncio.objects.filter(pk=a.pk).exists())
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('avisos:crear')).status_code, 200)

    def test_crear_con_pdf_y_validaciones(self):
        self.client.force_login(self.admin)
        datos = {'titulo': 'Circular', 'mensaje': '', 'importancia': 'normal', 'dest_profesionales': 'on',
                 'fecha_inicio': hoy().isoformat(), 'fecha_fin': hoy().isoformat(), 'guardar_en_historial': 'on'}
        # sin mensaje ni archivo → error
        r = self.client.post(reverse('avisos:crear'), datos)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Anuncio.objects.count(), 0)
        # extensión no permitida
        r = self.client.post(reverse('avisos:crear'), {**datos, 'adjunto': SimpleUploadedFile('x.exe', b'MZ')})
        self.assertEqual(Anuncio.objects.count(), 0)
        # PDF válido
        r = self.client.post(reverse('avisos:crear'), {**datos, 'adjunto': SimpleUploadedFile('c.pdf', b'%PDF-1.4')})
        self.assertEqual(r.status_code, 302)
        a = Anuncio.objects.get()
        self.assertEqual(a.adjunto_tipo(), 'pdf')
        self.assertEqual(a.creado_por, self.admin)
        a.delete()    # borra también el archivo
        # fecha fin anterior
        r = self.client.post(reverse('avisos:crear'), {**datos, 'mensaje': 'x', 'fecha_fin': (hoy() - timedelta(days=1)).isoformat()})
        self.assertEqual(Anuncio.objects.count(), 0)

    def test_confirmacion_de_lectura(self):
        sin = self.anuncio(pedir_confirmacion=False)
        con = self.anuncio(pedir_confirmacion=True)
        self.client.force_login(self.user_pac)
        self.assertEqual(self.client.post(reverse('avisos:leido', args=[sin.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('avisos:leido', args=[con.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse('avisos:leido', args=[con.pk])).status_code, 200)   # idempotente
        self.assertEqual(AnuncioLectura.objects.filter(anuncio=con).count(), 1)
        self.assertEqual(self.client.get(reverse('avisos:leido', args=[con.pk])).status_code, 405)
        # sigue visible aunque haya confirmado
        r = self.client.get(reverse('avisos:popup_data')).json()
        self.assertEqual({a['id'] for a in r['anuncios']}, {sin.id, con.id})
        # quien no es destinatario no puede confirmar
        self.client.force_login(self.rec1)
        self.assertEqual(self.client.post(reverse('avisos:leido', args=[con.pk])).status_code, 403)

    def test_pagina_avisos_menu_antes_de_temas(self):
        self.anuncio()
        for u in (self.admin, self.gerente, self.rec1, self.prof, self.user_pac):
            self.client.force_login(u)
            html = self.client.get(reverse('avisos:lista')).content.decode()
            self.assertIn('Aviso', html)
            self.assertLess(html.index('Avisos (antes de Temas)'), html.index('id="theme-nav-btn"'), u.username)

    def test_lista_vigentes_e_historial(self):
        fin = hoy() - timedelta(days=2)
        self.anuncio(titulo='Vigente X')
        self.anuncio(titulo='Historico Y', fecha_inicio=fin, fecha_fin=fin)
        self.anuncio(titulo='Borrado Z', fecha_inicio=fin, fecha_fin=fin, guardar_en_historial=False)
        self.client.force_login(self.user_pac)
        r = self.client.get(reverse('avisos:lista'))
        self.assertEqual([a.titulo for a in r.context['vigentes']], ['Vigente X'])
        self.assertEqual([a.titulo for a in r.context['historial']], ['Historico Y'])

    def test_context_processor_inicio_y_badge(self):
        self.anuncio()
        self.client.force_login(self.user_pac)
        r = self.client.get(reverse('facturacion:mi_cuenta'))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['avisos_es_inicio'])
        self.assertEqual(r.context['avisos_badge'], 1)
        self.assertIn('id="av-ov"', r.content.decode())
        r = self.client.get(reverse('facturacion:mis_deudas'))
        self.assertFalse(r.context['avisos_es_inicio'])
        self.assertNotIn('id="av-ov"', r.content.decode())

    def test_popup_solo_en_la_pagina_de_inicio_de_cada_rol(self):
        casos = [
            (self.admin, 'core:dashboard', True), (self.admin, 'agenda:calendario', False),
            (self.gerente, 'core:dashboard', True), (self.gerente, 'agenda:calendario', False),
            (self.rec1, 'core:dashboard', True), (self.rec1, 'agenda:calendario', False),
            (self.prof, 'agenda:calendario', True),
            (self.user_pac, 'facturacion:mi_cuenta', True), (self.user_pac, 'facturacion:mis_deudas', False),
        ]
        for u, nombre, esperado in casos:
            self.client.force_login(u)
            r = self.client.get(reverse(nombre))
            self.assertEqual(r.status_code, 200, (u.username, nombre))
            self.assertEqual(r.context['avisos_es_inicio'], esperado, (u.username, nombre))
            self.assertEqual('id="av-ov"' in r.content.decode(), esperado, (u.username, nombre))
        # filtros / vistas del calendario del profesional siguen siendo su inicio, pero el servidor
        # solo lo muestra una vez (ver test anterior)
        self.client.force_login(self.prof)
        r = self.client.get(reverse('agenda:calendario') + '?vista=mensual&sucursal=1')
        self.assertTrue(r.context['avisos_es_inicio'])


class RestriccionWhatsappTests(Base):
    API = ['recordatorios:whatsapp-status', 'recordatorios:whatsapp-qr', 'recordatorios:whatsapp-pausa',
           'recordatorios:whatsapp-historial', 'recordatorios:whatsapp-logs']
    PAGINAS = ['recordatorios:bots-monitor', 'recordatorios:logs-whatsapp']

    def test_profesional_y_paciente_bloqueados(self):
        for u in (self.prof, self.user_pac):
            self.client.force_login(u)
            for n in self.API:
                self.assertEqual(self.client.get(reverse(n)).status_code, 403, (u.username, n))
            for n in ('recordatorios:whatsapp-reconectar', 'recordatorios:whatsapp-envio-masivo'):
                self.assertEqual(self.client.post(reverse(n), '{}', content_type='application/json').status_code, 403)
            for n in self.PAGINAS:
                self.assertEqual(self.client.get(reverse(n)).status_code, 302, (u.username, n))
            self.assertEqual(self.client.get(reverse('recordatorios:backup_monitor')).status_code, 302)

    def test_personal_autorizado_pasa(self):
        for u in (self.admin, self.gerente, self.rec1):
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse('recordatorios:whatsapp-qr')).status_code, 200, u.username)
            self.assertEqual(self.client.get(reverse('recordatorios:bots-monitor')).status_code, 200, u.username)

    def test_respaldos_solo_admin(self):
        self.client.force_login(self.gerente)
        self.assertEqual(self.client.get(reverse('recordatorios:backup_monitor')).status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('recordatorios:backup_monitor')).status_code, 200)

    def test_post_sin_csrf_rechazado(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.admin)
        self.assertEqual(c.post(reverse('recordatorios:whatsapp-pausa'), '{"bot":"japon","pausar":false}',
                                content_type='application/json').status_code, 403)
