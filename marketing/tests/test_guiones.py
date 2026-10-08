import json
import os
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from marketing.guiones import (
    GuionError, aprobar_guion, construir_contexto, construir_prompt, crear_guion_manual,
    generar_guiones, normalizar_guion,
)
from marketing.models import AuditoriaMarketing, Campana, ConfigMarketing, FichaContenido, Marca
from marketing.proveedores.base import (
    ProveedorError, ProveedorNoDisponible, ProveedorTexto, RespuestaTexto, extraer_json,
)
from marketing.proveedores.registro import listar_proveedores_texto, obtener_proveedor_texto


def guion_json(**kw):
    d = {
        'gancho': '¿Tu hijo necesita apoyo para hablar?',
        'escenas': [
            {'texto_pantalla': 'Terapia de lenguaje', 'locucion': 'Te acompañamos.', 'prompt_visual': 'zoom lento',
             'duracion_seg': 5},
            {'texto_pantalla': 'Agenda tu evaluación', 'locucion': 'Escríbenos.', 'prompt_visual': 'fachada',
             'duracion_seg': 4},
        ],
        'caption': 'Agenda tu evaluación por WhatsApp.', 'hashtags': ['#potosi', 'terapia'],
    }
    d.update(kw)
    return json.dumps(d)


class ProveedorFalso(ProveedorTexto):
    id = 'falso'
    nombre = 'Falso'

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.prompts = []

    def generar(self, sistema, usuario, temperatura=0.8):
        self.prompts.append((sistema, usuario))
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return RespuestaTexto(texto=r, modelo='falso-1')


class BaseGuionTests(TestCase):
    def setUp(self):
        call_command('cargar_marcas_iniciales', verbosity=0)
        self.dueno = User.objects.create_superuser('d', 'd@x.com', 'x')
        self.marca = Marca.objects.get(slug='centro-misael')
        self.ficha = FichaContenido.objects.create(
            marca=self.marca, titulo='Terapia de lenguaje', texto='SERVICIO: Terapia de lenguaje. Atendemos niños.',
            aprobada=True,
        )
        self.sin_aprobar = FichaContenido.objects.create(
            marca=self.marca, titulo='SECRETO', texto='TEXTO_NO_APROBADO_XYZ', aprobada=False,
        )
        self.campana = Campana.objects.create(marca=self.marca, titulo='Lenguaje', redes=['instagram'])
        self.campana.fichas.add(self.ficha, self.sin_aprobar)


class ContextoYPromptTests(BaseGuionTests):
    def test_solo_fichas_aprobadas_en_contexto_y_prompt(self):
        ctx = construir_contexto(self.campana)
        self.assertEqual([f['titulo'] for f in ctx['fichas']], ['Terapia de lenguaje'])
        sistema, usuario = construir_prompt(ctx, 'informativo')
        self.assertIn('Terapia de lenguaje', usuario)
        self.assertNotIn('TEXTO_NO_APROBADO_XYZ', usuario)

    def test_sin_fichas_aprobadas_falla(self):
        self.campana.fichas.clear()
        self.campana.fichas.add(self.sin_aprobar)
        with self.assertRaises(GuionError):
            construir_contexto(self.campana)

    def test_prompt_incluye_reglas_de_marca_y_prohibidas(self):
        ctx = construir_contexto(self.campana)
        _, usuario = construir_prompt(ctx, 'x')
        self.assertIn('curar', usuario)
        self.assertIn('NO, no menciones precios', usuario)

    def test_prompt_pide_ilustracion_en_ia_total(self):
        self.campana.origen_visual = 'ia_total'
        ctx = construir_contexto(self.campana)
        _, usuario = construir_prompt(ctx, 'x')
        self.assertIn('NUNCA fotorrealistas', usuario)

    def test_prompt_propias_pide_solo_movimiento(self):
        ctx = construir_contexto(self.campana)
        _, usuario = construir_prompt(ctx, 'x')
        self.assertIn('FOTOS REALES', usuario)

    def test_no_se_incluyen_activos_sin_autorizacion(self):
        from marketing.models import Activo
        malo = Activo.objects.create(marca=self.marca, nombre='FOTO_NINO', archivo='a.jpg',
                                     contiene_menores=True, contiene_personas=True)
        bueno = Activo.objects.create(marca=self.marca, nombre='FACHADA', archivo='b.jpg')
        self.campana.activos_referencia.add(malo, bueno)
        ctx = construir_contexto(self.campana)
        self.assertEqual([r['nombre'] for r in ctx['referencias']], ['FACHADA'])

    def test_contexto_no_trae_datos_personales_del_profesional(self):
        from profesionales.models import Profesional
        u = User.objects.create_user('pp', 'secreto@x.com', 'x')
        p = Profesional.objects.create(user=u, nombre='Ana', apellido='R', especialidad='Psicología',
                                       telefono='70099999', email='secreto@x.com')
        self.campana.profesional = p
        ctx = construir_contexto(self.campana)
        self.assertNotIn('70099999', json.dumps(ctx))
        self.assertNotIn('secreto@x.com', json.dumps(ctx))


class GenerarGuionesTests(BaseGuionTests):
    def test_guion_valido(self):
        prov = ProveedorFalso([guion_json()])
        [g] = generar_guiones(self.campana, proveedor=prov, usuario=self.dueno)
        self.assertEqual(g.estado, 'validado')
        self.assertEqual(g.version, 1)
        self.assertEqual(g.generado_por, 'ia')
        self.assertEqual(g.modelo_texto, 'falso-1')
        self.assertTrue(g.validacion['valido'])
        self.assertIn('titulo', g.datos_fuente['fichas'][0])
        self.assertTrue(AuditoriaMarketing.objects.filter(accion='guion_generado').exists())

    def test_hashtags_normalizados_y_base_agregada(self):
        self.marca.hashtags_base = '#CentroMisael'
        self.marca.save()
        prov = ProveedorFalso([guion_json(hashtags=['#potosi', 'terapia', '#Potosí!'])])
        [g] = generar_guiones(self.campana, proveedor=prov)
        tags = g.hashtags.split()
        self.assertIn('#terapia', tags)
        self.assertIn('#CentroMisael', tags)
        self.assertTrue(all(t.startswith('#') for t in tags))

    def test_versiones_incrementales(self):
        prov = ProveedorFalso([guion_json(), guion_json()])
        a = generar_guiones(self.campana, proveedor=prov)[0]
        b = generar_guiones(self.campana, proveedor=prov)[0]
        self.assertEqual((a.version, b.version), (1, 2))

    def test_varias_variantes_usan_enfoques_distintos(self):
        prov = ProveedorFalso([guion_json(), guion_json(), guion_json()])
        gs = generar_guiones(self.campana, cantidad=3, proveedor=prov)
        self.assertEqual(len(gs), 3)
        enfoques = {u.split('ENFOQUE PARA ESTE GUION:')[1].split('\n')[0] for _, u in prov.prompts}
        self.assertEqual(len(enfoques), 3)

    def test_reparacion_con_errores_funciona(self):
        malo = guion_json(caption='Esto cura todo')
        bueno = guion_json()
        prov = ProveedorFalso([malo, bueno])
        [g] = generar_guiones(self.campana, proveedor=prov)
        self.assertEqual(g.estado, 'validado')
        self.assertEqual(len(prov.prompts), 2)
        self.assertIn('RECHAZADA', prov.prompts[1][1])
        self.assertIn('cura', prov.prompts[1][1])

    def test_si_la_reparacion_tambien_falla_queda_rechazado_con_errores(self):
        prov = ProveedorFalso([guion_json(caption='cura'), guion_json(caption='cura de nuevo')])
        [g] = generar_guiones(self.campana, proveedor=prov)
        self.assertEqual(g.estado, 'rechazado')
        self.assertTrue(g.validacion['errores'])

    def test_si_la_reparacion_cae_por_red_se_conserva_la_primera_rechazada(self):
        prov = ProveedorFalso([guion_json(caption='cura'), ProveedorError('sin red')])
        [g] = generar_guiones(self.campana, proveedor=prov)
        self.assertEqual(g.estado, 'rechazado')

    def test_json_invalido_reintenta_y_luego_funciona(self):
        prov = ProveedorFalso(['esto no es json', guion_json()])
        [g] = generar_guiones(self.campana, proveedor=prov)
        self.assertEqual(g.estado, 'validado')

    def test_json_invalido_dos_veces_lanza_error(self):
        prov = ProveedorFalso(['basura', 'más basura'])
        with self.assertRaises(ProveedorError):
            generar_guiones(self.campana, proveedor=prov)

    def test_error_del_proveedor_se_propaga(self):
        with self.assertRaises(ProveedorError):
            generar_guiones(self.campana, proveedor=ProveedorFalso([ProveedorError('cuota'), ProveedorError('cuota')]))

    def test_campana_donde_el_usuario_escribe_no_usa_ia(self):
        self.campana.quien_escribe = 'usuario'
        with self.assertRaises(GuionError):
            generar_guiones(self.campana, proveedor=ProveedorFalso([guion_json()]))

    def test_duracion_se_acota(self):
        prov = ProveedorFalso([guion_json(escenas=[
            {'texto_pantalla': 'a', 'locucion': 'b', 'prompt_visual': 'c', 'duracion_seg': 999},
            {'texto_pantalla': 'a', 'locucion': 'b', 'prompt_visual': 'c', 'duracion_seg': 'abc'},
        ])])
        [g] = generar_guiones(self.campana, proveedor=prov)
        self.assertEqual([e['duracion_seg'] for e in g.escenas], [15.0, 4.0])

    def test_cantidad_se_acota_a_3(self):
        prov = ProveedorFalso([guion_json()] * 3)
        self.assertEqual(len(generar_guiones(self.campana, cantidad=99, proveedor=prov)), 3)

    def test_ia_inventa_telefono_queda_rechazado(self):
        prov = ProveedorFalso([guion_json(caption='Llama al 71234567')] * 2)
        [g] = generar_guiones(self.campana, proveedor=prov)
        self.assertEqual(g.estado, 'rechazado')
        self.assertTrue(any(e['regla'] == 'telefono' for e in g.validacion['errores']))


class ManualYAprobacionTests(BaseGuionTests):
    def _manual(self, **kw):
        datos = dict(gancho='Hola familia', escenas=[{'texto_pantalla': 'a', 'locucion': 'b', 'duracion_seg': 5}],
                     caption='Agenda tu evaluación', hashtags='#a')
        datos.update(kw)
        return crear_guion_manual(self.campana, usuario=self.dueno, **datos)

    def test_manual_se_valida_igual(self):
        self.assertEqual(self._manual().estado, 'validado')
        self.assertEqual(self._manual(caption='garantizado').estado, 'rechazado')

    def test_aprobar_valido(self):
        g = aprobar_guion(self._manual(), self.dueno)
        self.assertEqual(g.estado, 'aprobado')
        self.assertTrue(AuditoriaMarketing.objects.filter(accion='guion_aprobado').exists())

    def test_no_se_aprueba_un_rechazado(self):
        with self.assertRaises(GuionError):
            aprobar_guion(self._manual(caption='garantizado'), self.dueno)

    def test_aprobar_revalida_con_reglas_actuales(self):
        g = self._manual()
        self.marca.palabras_prohibidas += '\nevaluación'
        self.marca.save()
        with self.assertRaises(GuionError):
            aprobar_guion(g, self.dueno)
        g.refresh_from_db()
        self.assertEqual(g.estado, 'rechazado')


class ProveedoresTests(TestCase):
    def test_extraer_json_tolerante(self):
        self.assertEqual(extraer_json('{"a": 1}'), {'a': 1})
        self.assertEqual(extraer_json('```json\n{"a": 1}\n```'), {'a': 1})
        self.assertEqual(extraer_json('Claro, aquí va: {"a": 1} listo'), {'a': 1})
        for malo in ('', '   ', 'sin json', '{roto'):
            with self.assertRaises(ProveedorError):
                extraer_json(malo)

    def test_disponibilidad_depende_de_la_clave(self):
        with mock.patch.dict(os.environ, {'GEMINI_API_KEY': '', 'GROQ_API_KEY': ''}):
            self.assertFalse(any(p['disponible'] for p in listar_proveedores_texto()))
            with self.assertRaises(ProveedorNoDisponible):
                obtener_proveedor_texto()
        with mock.patch.dict(os.environ, {'GEMINI_API_KEY': 'k', 'GROQ_API_KEY': ''}):
            self.assertEqual(obtener_proveedor_texto().id, 'gemini')

    def test_pedido_explicito_sin_clave_no_cambia_en_silencio(self):
        with mock.patch.dict(os.environ, {'GEMINI_API_KEY': 'k', 'GROQ_API_KEY': ''}):
            with self.assertRaises(ProveedorNoDisponible):
                obtener_proveedor_texto('groq')

    def test_respeta_el_proveedor_configurado(self):
        c = ConfigMarketing.get(); c.proveedor_texto = 'groq'; c.save()
        with mock.patch.dict(os.environ, {'GEMINI_API_KEY': 'k', 'GROQ_API_KEY': 'k'}):
            self.assertEqual(obtener_proveedor_texto().id, 'groq')
        c.proveedor_texto = 'groq'; c.save()
        with mock.patch.dict(os.environ, {'GEMINI_API_KEY': 'k', 'GROQ_API_KEY': ''}):
            self.assertEqual(obtener_proveedor_texto().id, 'gemini')  # el configurado no tiene clave -> siguiente
