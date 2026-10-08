from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, override_settings

from marketing.proveedores.base import ProveedorError
from marketing.proveedores.texto_gemini import GeminiTexto
from marketing.storage_backends import (
    MarketingNoConfiguradoStorage, R2MarketingStorage, get_marketing_storage,
)
from marketing.storage_cloudinary import CloudinaryMarketingStorage, tipo_recurso

CRED = {'cloud_name': 'demo', 'api_key': '123', 'api_secret': 'secreto'}


def _resp(status=200, json=None):
    r = mock.Mock(status_code=status, text='x')
    r.json.return_value = json if json is not None else {}
    return r


class GeminiTextoTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.dict('os.environ', {'GEMINI_API_KEY': 'k'})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_modelo_por_defecto_y_override(self):
        self.assertEqual(GeminiTexto().modelo, 'gemini-3.5-flash')
        with mock.patch.dict('os.environ', {'MARKETING_GEMINI_MODEL': 'otro-modelo'}):
            self.assertEqual(GeminiTexto().modelo, 'otro-modelo')

    @mock.patch('marketing.proveedores.texto_gemini.requests.post')
    def test_respuesta_correcta(self, post):
        post.return_value = _resp(json={
            'candidates': [{'content': {'parts': [{'text': '{"ok": true}'}]}}],
            'usageMetadata': {'promptTokenCount': 10, 'candidatesTokenCount': 5, 'thoughtsTokenCount': 20},
        })
        r = GeminiTexto().generar('sis', 'usu', temperatura=0.5)
        self.assertEqual(r.texto, '{"ok": true}')
        self.assertEqual((r.tokens_entrada, r.tokens_salida), (10, 25))
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs['headers']['x-goog-api-key'], 'k')
        self.assertNotIn('temperature', kwargs['json']['generationConfig'])  # Gemini 3
        self.assertEqual(len(kwargs['json']['safetySettings']), 4)
        self.assertTrue(all(s['threshold'] == 'BLOCK_MEDIUM_AND_ABOVE' for s in kwargs['json']['safetySettings']))

    @mock.patch('marketing.proveedores.texto_gemini.requests.post')
    def test_temperatura_en_modelos_anteriores(self, post):
        post.return_value = _resp(json={'candidates': [{'content': {'parts': [{'text': '{}'}]}}]})
        with mock.patch.dict('os.environ', {'MARKETING_GEMINI_MODEL': 'gemini-2.0-flash'}):
            GeminiTexto().generar('s', 'u', temperatura=0.3)
        self.assertEqual(post.call_args.kwargs['json']['generationConfig']['temperature'], 0.3)

    @mock.patch('marketing.proveedores.texto_gemini.requests.post')
    def test_ignora_partes_de_razonamiento(self, post):
        post.return_value = _resp(json={'candidates': [{'content': {'parts': [
            {'text': 'pensando', 'thought': True}, {'text': '{"a": 1}'},
        ]}}]})
        self.assertEqual(GeminiTexto().generar('s', 'u').texto, '{"a": 1}')

    @mock.patch('marketing.proveedores.texto_gemini.requests.post')
    def test_errores(self, post):
        casos = [
            _resp(404, {'error': {'message': 'no longer available'}}),
            _resp(json={'promptFeedback': {'blockReason': 'SAFETY'}}),
            _resp(json={'candidates': []}),
            _resp(json={'candidates': [{'content': {'parts': []}, 'finishReason': 'SAFETY'}]}),
        ]
        for caso in casos:
            post.return_value = caso
            with self.assertRaises(ProveedorError):
                GeminiTexto().generar('s', 'u')

    @mock.patch('marketing.proveedores.texto_gemini.requests.post', side_effect=__import__('requests').ConnectionError('x'))
    def test_error_de_red(self, _):
        with self.assertRaises(ProveedorError):
            GeminiTexto().generar('s', 'u')


class CloudinaryStorageTests(SimpleTestCase):
    def storage(self, tipo='authenticated'):
        return CloudinaryMarketingStorage(**CRED, tipo=tipo)

    def test_exige_credenciales(self):
        with self.assertRaises(ImproperlyConfigured):
            CloudinaryMarketingStorage(cloud_name='x')

    def test_tipo_de_recurso(self):
        self.assertEqual(tipo_recurso('a/b.JPG'), 'image')
        self.assertEqual(tipo_recurso('a.mp4'), 'video')
        self.assertEqual(tipo_recurso('a.mp3'), 'video')
        self.assertEqual(tipo_recurso('a.pdf'), 'raw')

    @mock.patch('cloudinary.uploader.upload')
    def test_guardar_imagen_usa_carpeta_marketing_y_credenciales_propias(self, upload):
        upload.side_effect = lambda f, **kw: {'public_id': kw['public_id'], 'format': 'jpg'}
        nombre = self.storage().save('activos/2026/10/Mi Foto.jpg', ContentFile(b'x'))
        kw = upload.call_args.kwargs
        self.assertTrue(kw['public_id'].startswith('marketing/activos/2026/10/Mi_Foto_'))
        self.assertNotIn('.jpg', kw['public_id'])
        self.assertEqual((kw['resource_type'], kw['type'], kw['overwrite']), ('image', 'authenticated', False))
        self.assertEqual(kw['cloud_name'], 'demo')
        self.assertTrue(nombre.startswith('marketing/activos/2026/10/Mi_Foto_') and nombre.endswith('.jpg'))

    @mock.patch('cloudinary.uploader.upload')
    def test_guardar_raw_conserva_extension(self, upload):
        upload.side_effect = lambda f, **kw: {'public_id': kw['public_id']}
        nombre = self.storage().save('docs/guia.pdf', ContentFile(b'x'))
        self.assertTrue(nombre.endswith('.pdf'))
        self.assertEqual(upload.call_args.kwargs['resource_type'], 'raw')

    @mock.patch('cloudinary.uploader.upload', side_effect=Exception('boom'))
    def test_error_al_subir(self, _):
        with self.assertRaises(OSError):
            self.storage().save('a.png', ContentFile(b'x'))

    def test_url_firmada_y_publica(self):
        firmada = self.storage().url('marketing/activos/foto_ab12.jpg')
        self.assertIn('res.cloudinary.com/demo/image/authenticated/', firmada)
        self.assertIn('s--', firmada)  # firma
        self.assertTrue(firmada.endswith('marketing/activos/foto_ab12.jpg'))
        publica = self.storage(tipo='upload').url('marketing/activos/foto_ab12.jpg')
        self.assertIn('/image/upload/', publica)
        self.assertNotIn('s--', publica)

    def test_url_de_video(self):
        self.assertIn('/video/authenticated/', self.storage().url('marketing/piezas/v_1.mp4'))

    @mock.patch('cloudinary.uploader.destroy')
    def test_borrar(self, destroy):
        self.storage().delete('marketing/activos/foto_ab12.jpg')
        args, kw = destroy.call_args
        self.assertEqual(args[0], 'marketing/activos/foto_ab12')
        self.assertEqual((kw['resource_type'], kw['type']), ('image', 'authenticated'))

    def test_exists_siempre_falso(self):
        self.assertFalse(self.storage().exists('lo/que/sea.png'))


class SelectorDeStorageTests(SimpleTestCase):
    CL = {'MARKETING_CLOUDINARY_CONFIGURADO': True, 'MARKETING_CLOUDINARY': CRED}

    @override_settings(MARKETING_R2_CONFIGURADO=False, MARKETING_STORAGE_BACKEND='', **CL)
    def test_automatico_usa_cloudinary_si_no_hay_r2(self):
        self.assertIsInstance(get_marketing_storage(), CloudinaryMarketingStorage)

    @override_settings(MARKETING_R2_CONFIGURADO=True, MARKETING_STORAGE_BACKEND='cloudinary', **CL)
    def test_forzar_cloudinary(self):
        self.assertIsInstance(get_marketing_storage(), CloudinaryMarketingStorage)

    @override_settings(MARKETING_R2_CONFIGURADO=True, MARKETING_STORAGE_BACKEND='r2', **CL)
    def test_forzar_r2(self):
        self.assertIsInstance(get_marketing_storage(), R2MarketingStorage)

    @override_settings(MARKETING_R2_CONFIGURADO=False, MARKETING_CLOUDINARY_CONFIGURADO=False,
                       MARKETING_STORAGE_BACKEND='cloudinary', IS_PRODUCTION=True)
    def test_elegido_sin_configurar_no_cae_al_storage_por_defecto(self):
        self.assertIsInstance(get_marketing_storage(), MarketingNoConfiguradoStorage)
