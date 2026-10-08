from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.core.exceptions import PermissionDenied

from marketing.models import (
    Activo, Campana, ConfigMarketing, FichaContenido, Marca, RegistroGasto,
)
from marketing.permissions import puede_usar_marketing, superusuario_requerido
from marketing.storage_backends import (
    MarketingNoConfiguradoStorage, R2MarketingStorage, get_marketing_storage,
)


class PermisosTests(TestCase):
    def setUp(self):
        self.dueno = User.objects.create_superuser('dueno', 'd@x.com', 'x')
        self.staff = User.objects.create_user('staff', 's@x.com', 'x', is_staff=True)

    def test_solo_superusuario(self):
        self.assertTrue(puede_usar_marketing(self.dueno))
        self.assertFalse(puede_usar_marketing(self.staff))

    def test_usuario_inactivo_no_accede(self):
        self.dueno.is_active = False
        self.assertFalse(puede_usar_marketing(self.dueno))

    def test_decorador(self):
        vista = superusuario_requerido(lambda request: 'ok')
        rf = RequestFactory()
        req = rf.get('/'); req.user = self.dueno
        self.assertEqual(vista(req), 'ok')
        req = rf.get('/'); req.user = self.staff
        with self.assertRaises(PermissionDenied):
            vista(req)

    def test_admin_oculto_para_staff(self):
        self.staff.is_superuser = False
        self.client.force_login(self.staff)
        resp = self.client.get('/admin/marketing/marca/')
        self.assertIn(resp.status_code, (302, 403))

    def test_admin_visible_para_superusuario(self):
        self.client.force_login(self.dueno)
        for nombre in ('marca', 'activo', 'campana', 'guion', 'pieza', 'publicacion',
                       'fichacontenido', 'registrogasto', 'auditoriamarketing', 'configmarketing'):
            resp = self.client.get(f'/admin/marketing/{nombre}/')
            self.assertEqual(resp.status_code, 200, nombre)


class ActivoConsentimientoTests(TestCase):
    def setUp(self):
        self.marca = Marca.objects.create(slug='m', nombre='M')

    def _activo(self, **kw):
        return Activo(marca=self.marca, nombre='a', archivo='x.jpg', **kw)

    def test_sin_personas_es_usable(self):
        self.assertTrue(self._activo().usable_en_publicidad)

    def test_personas_sin_autorizacion_no_usable(self):
        self.assertFalse(self._activo(contiene_personas=True).usable_en_publicidad)

    def test_personas_con_autorizacion_usable(self):
        self.assertTrue(self._activo(contiene_personas=True, autorizacion_confirmada=True).usable_en_publicidad)

    def test_menores_sin_autorizacion_no_usable(self):
        self.assertFalse(self._activo(contiene_menores=True).usable_en_publicidad)

    def test_menores_autorizacion_sin_referencia_no_usable(self):
        a = self._activo(contiene_menores=True, autorizacion_confirmada=True)
        self.assertFalse(a.usable_en_publicidad)
        with self.assertRaises(ValidationError):
            a.clean()

    def test_menores_con_autorizacion_y_referencia_usable(self):
        a = self._activo(contiene_menores=True, autorizacion_confirmada=True, autorizacion_nota='Carpeta 2026 #14')
        a.clean()
        self.assertTrue(a.usable_en_publicidad)

    def test_menores_implica_personas(self):
        a = self._activo(contiene_menores=True)
        a.clean()
        self.assertTrue(a.contiene_personas)

    def test_inactivo_no_usable(self):
        self.assertFalse(self._activo(activo=False).usable_en_publicidad)


class ConfigYGastoTests(TestCase):
    def test_config_es_singleton(self):
        ConfigMarketing.objects.create(presupuesto_mensual_usd=Decimal('10'))
        ConfigMarketing.objects.create(presupuesto_mensual_usd=Decimal('30'))
        self.assertEqual(ConfigMarketing.objects.count(), 1)
        self.assertEqual(ConfigMarketing.get().presupuesto_mensual_usd, Decimal('30'))

    def test_config_no_se_borra(self):
        c = ConfigMarketing.get()
        c.delete()
        self.assertEqual(ConfigMarketing.objects.count(), 1)

    def test_ninos_realistas_apagado_por_defecto(self):
        self.assertFalse(ConfigMarketing.get().ia_permite_ninos_realistas)

    def test_total_mes(self):
        RegistroGasto.objects.create(proveedor='x', monto_usd=Decimal('1.50'))
        RegistroGasto.objects.create(proveedor='y', monto_usd=Decimal('2.25'))
        self.assertEqual(RegistroGasto.total_mes(), Decimal('3.75'))


class MarcaYFichaTests(TestCase):
    def test_palabras_prohibidas_normalizadas(self):
        m = Marca(slug='a', nombre='A', palabras_prohibidas='Cura\n\n  Garantizado \n')
        self.assertEqual(m.lista_palabras_prohibidas, ['cura', 'garantizado'])

    def test_color_invalido(self):
        m = Marca(slug='a', nombre='A', color_primario='azul')
        with self.assertRaises(ValidationError):
            m.full_clean()

    def test_ficha_unica_por_fuente(self):
        from django.db import IntegrityError, transaction
        m = Marca.objects.create(slug='a', nombre='A')
        FichaContenido.objects.create(marca=m, titulo='t', texto='x', fuente='servicios_data', clave_fuente='s1')
        with self.assertRaises(IntegrityError), transaction.atomic():
            FichaContenido.objects.create(marca=m, titulo='t2', texto='y', fuente='servicios_data', clave_fuente='s1')
        # fichas manuales sin clave no chocan entre sí
        FichaContenido.objects.create(marca=m, titulo='a', texto='x')
        FichaContenido.objects.create(marca=m, titulo='b', texto='y')

    def test_campana_valida_redes(self):
        m = Marca.objects.create(slug='a', nombre='A')
        c = Campana(marca=m, titulo='c', redes=['instagram', 'myspace'])
        with self.assertRaises(ValidationError):
            c.clean()
        c.redes = ['instagram', 'tiktok']
        c.clean()

    def test_comando_marcas_idempotente_y_no_pisa_ediciones(self):
        call_command('cargar_marcas_iniciales', verbosity=0)
        self.assertEqual(Marca.objects.count(), 3)
        Marca.objects.filter(slug='misael-kids').update(cierre_fijo='MI TEXTO')
        call_command('cargar_marcas_iniciales', verbosity=0)
        self.assertEqual(Marca.objects.count(), 3)
        self.assertEqual(Marca.objects.get(slug='misael-kids').cierre_fijo, 'MI TEXTO')
        self.assertFalse(Marca.objects.get(slug='centro-misael').permite_precios)
        self.assertTrue(Marca.objects.get(slug='misael-toys').permite_precios)


class StorageTests(TestCase):
    @override_settings(MARKETING_R2_CONFIGURADO=True)
    def test_con_r2_configurado_usa_r2(self):
        self.assertIsInstance(get_marketing_storage(), R2MarketingStorage)

    @override_settings(MARKETING_R2_CONFIGURADO=False, IS_PRODUCTION=True)
    def test_produccion_sin_config_no_cae_al_default_y_bloquea_guardado(self):
        from django.core.files.base import ContentFile
        st = get_marketing_storage()
        self.assertIsInstance(st, MarketingNoConfiguradoStorage)
        with self.assertRaises(ImproperlyConfigured):
            st.save('x.txt', ContentFile(b'hola'))

    @override_settings(MARKETING_R2_CONFIGURADO=False, IS_PRODUCTION=False)
    def test_desarrollo_usa_carpeta_local_de_marketing(self):
        from django.core.files.storage import FileSystemStorage
        st = get_marketing_storage()
        self.assertIsInstance(st, FileSystemStorage)
        self.assertNotIsInstance(st, MarketingNoConfiguradoStorage)
        self.assertTrue(str(st.location).replace('\\', '/').endswith('media/marketing'))
