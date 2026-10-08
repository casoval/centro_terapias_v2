from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from unittest import mock

from core.servicios_data import SERVICIOS_PUBLICOS
from marketing import fuentes
from marketing.models import FichaContenido, Marca
from marketing.sincronizacion import huella, sincronizar_fichas_centro
from profesionales.models import Profesional
from servicios.models import Sucursal, TipoServicio


class FuentesTests(TestCase):
    def test_servicios_publicos(self):
        lista = fuentes.listar_servicios_publicos()
        self.assertEqual(len(lista), len(SERVICIOS_PUBLICOS))
        self.assertTrue(all({'slug', 'nombre'} <= set(s) for s in lista))

    def test_texto_ficha_excluye_seo_y_trae_contenido(self):
        s = next(iter(SERVICIOS_PUBLICOS.values()))
        t = fuentes.texto_ficha_servicio(s)
        self.assertIn(s['nombre'], t)
        self.assertIn(s['condiciones'][0], t)
        self.assertIn(s['faqs'][0]['q'], t)
        self.assertNotIn(s['title_tag'], t)
        self.assertNotIn(s['meta_description'], t)

    def test_profesional_no_expone_datos_personales(self):
        u = User.objects.create_user('p1', 'privado@x.com', 'x')
        p = Profesional.objects.create(
            user=u, nombre='Ana', apellido='Rojas', especialidad='Psicología',
            telefono='70000000', email='privado@x.com',
        )
        d = fuentes.datos_profesional(p.pk)
        self.assertEqual(set(d), {'id', 'nombre_completo', 'especialidad'})
        self.assertNotIn('70000000', str(d))
        self.assertNotIn('privado@x.com', str(d))

    def test_profesional_inactivo_no_se_entrega(self):
        u = User.objects.create_user('p2', 'x@x.com', 'x')
        p = Profesional.objects.create(user=u, nombre='B', apellido='C', especialidad='X', activo=False)
        self.assertIsNone(fuentes.datos_profesional(p.pk))

    def test_precio_solo_si_se_pide(self):
        t = TipoServicio.objects.create(nombre='Terapia X', costo_base=100)
        sin = fuentes.datos_tipo_servicio(t.pk)
        con = fuentes.datos_tipo_servicio(t.pk, incluir_precio=True)
        self.assertNotIn('costo_base', sin)
        self.assertEqual(con['costo_base'], '100.00')

    def test_sucursales_solo_activas(self):
        Sucursal.objects.create(nombre='A', direccion='Calle 1', telefono='111', activa=True)
        Sucursal.objects.create(nombre='B', direccion='Calle 2', activa=False)
        self.assertEqual([s['nombre'] for s in fuentes.datos_sucursales()], ['A'])
        self.assertEqual(len(fuentes.datos_sucursales(solo_activas=False)), 2)


class SincronizacionTests(TestCase):
    def setUp(self):
        call_command('cargar_marcas_iniciales', verbosity=0)
        Sucursal.objects.create(nombre='Sede Uno', direccion='Av. Principal 123', telefono='76175352')

    def test_sin_marca_da_error_claro(self):
        Marca.objects.all().delete()
        with self.assertRaises(ValueError):
            sincronizar_fichas_centro()

    def test_crea_fichas_sin_aprobar(self):
        r = sincronizar_fichas_centro()
        self.assertEqual(r['creadas'], len(SERVICIOS_PUBLICOS) + 1)  # servicios + sedes
        self.assertFalse(FichaContenido.objects.filter(aprobada=True).exists())
        sedes = FichaContenido.objects.get(clave_fuente='sedes')
        self.assertIn('Av. Principal 123', sedes.texto)

    def test_idempotente(self):
        sincronizar_fichas_centro()
        r = sincronizar_fichas_centro()
        self.assertEqual(r['creadas'], 0)
        self.assertEqual(r['sin_cambios'], len(SERVICIOS_PUBLICOS) + 1)

    def test_cambio_en_fuente_actualiza_y_quita_aprobacion(self):
        sincronizar_fichas_centro()
        slug = next(iter(SERVICIOS_PUBLICOS))
        FichaContenido.objects.filter(clave_fuente=slug).update(aprobada=True)
        with mock.patch('marketing.sincronizacion.fichas_servicios_publicos') as m:
            m.return_value = [{'clave': slug, 'titulo': 'Nuevo título', 'texto': 'Texto nuevo', 'tipo': 'servicio'}]
            r = sincronizar_fichas_centro()
        f = FichaContenido.objects.get(clave_fuente=slug)
        self.assertEqual(r['actualizadas'], 1)
        self.assertEqual(f.texto, 'Texto nuevo')
        self.assertFalse(f.aprobada)

    def test_edicion_manual_no_se_pisa(self):
        sincronizar_fichas_centro()
        slug = next(iter(SERVICIOS_PUBLICOS))
        f = FichaContenido.objects.get(clave_fuente=slug)
        f.texto = 'MI VERSIÓN EDITADA'
        f.aprobada = True
        f.save()
        with mock.patch('marketing.sincronizacion.fichas_servicios_publicos') as m:
            m.return_value = [{'clave': slug, 'titulo': 'X', 'texto': 'Texto distinto de la fuente', 'tipo': 'servicio'}]
            r = sincronizar_fichas_centro()
        f.refresh_from_db()
        self.assertEqual(r['conservadas_editadas'], 1)
        self.assertEqual(f.texto, 'MI VERSIÓN EDITADA')
        self.assertTrue(f.aprobada)

    def test_huella_estable(self):
        self.assertEqual(huella('a'), huella('a'))
        self.assertNotEqual(huella('a'), huella('b'))
