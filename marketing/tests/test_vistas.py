import io
import os
import shutil
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from marketing.models import (
    Activo, AuditoriaMarketing, Campana, ConfigMarketing, FichaContenido, Guion, Marca,
)
from marketing.storage_backends import MarketingNoConfiguradoStorage
from marketing.tests.test_guiones import ProveedorFalso, guion_json
from servicios.models import Sucursal

PAGINAS_GET = [
    ('marketing:panel', []), ('marketing:campana_lista', []), ('marketing:campana_crear', []),
    ('marketing:ficha_lista', []), ('marketing:ficha_crear', []), ('marketing:marca_lista', []),
    ('marketing:activo_lista', []), ('marketing:activo_subir', []), ('marketing:config', []),
]


def png(nombre='foto.png', tam=(20, 20)):
    buf = io.BytesIO()
    Image.new('RGB', tam, 'blue').save(buf, 'PNG')
    return SimpleUploadedFile(nombre, buf.getvalue(), content_type='image/png')


class Base(TestCase):
    def setUp(self):
        call_command('cargar_marcas_iniciales', verbosity=0)
        self.dueno = User.objects.create_superuser('dueno', 'd@x.com', 'x')
        self.marca = Marca.objects.get(slug='centro-misael')
        self.ficha = FichaContenido.objects.create(
            marca=self.marca, titulo='Lenguaje', texto='SERVICIO: Terapia de lenguaje.', aprobada=True)
        self.campana = Campana.objects.create(marca=self.marca, titulo='Camp', redes=['instagram'])
        self.campana.fichas.add(self.ficha)
        self.client.force_login(self.dueno)


class AccesoTests(Base):
    def _urls(self):
        urls = [reverse(n, args=a) for n, a in PAGINAS_GET]
        urls += [reverse('marketing:campana_detalle', args=[self.campana.pk]),
                 reverse('marketing:campana_editar', args=[self.campana.pk]),
                 reverse('marketing:guion_manual', args=[self.campana.pk]),
                 reverse('marketing:ficha_editar', args=[self.ficha.pk]),
                 reverse('marketing:marca_editar', args=[self.marca.pk])]
        return urls

    def test_superusuario_abre_todas_las_paginas(self):
        for url in self._urls():
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_anonimo_va_al_login(self):
        self.client.logout()
        for url in self._urls():
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn('/login', r.url)

    def test_gerente_no_accede(self):
        g = User.objects.create_user('ger', 'g@x.com', 'x')
        g.perfil.rol = 'gerente'
        g.perfil.save()
        self.client.force_login(g)
        for url in self._urls():
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_staff_no_accede(self):
        s = User.objects.create_user('st', 's@x.com', 'x', is_staff=True)
        self.client.force_login(s)
        self.assertEqual(self.client.get(reverse('marketing:panel')).status_code, 403)

    def test_acciones_exigen_post_y_superusuario(self):
        posts = [reverse('marketing:ficha_sincronizar'),
                 reverse('marketing:ficha_aprobar', args=[self.ficha.pk]),
                 reverse('marketing:campana_archivar', args=[self.campana.pk]),
                 reverse('marketing:guion_generar', args=[self.campana.pk])]
        for url in posts:
            self.assertEqual(self.client.get(url).status_code, 405, url)   # GET no sirve
        otro = User.objects.create_user('otro', 'o@x.com', 'x')
        self.client.force_login(otro)
        for url in posts:
            self.assertEqual(self.client.post(url).status_code, 403, url)  # no superusuario
        self.ficha.refresh_from_db()
        self.assertTrue(self.ficha.aprobada)


class MenuTests(Base):
    def test_superusuario_ve_el_menu_antes_de_temas(self):
        html = self.client.get(reverse('marketing:panel')).content.decode()
        self.assertIn(reverse('marketing:campana_lista'), html)
        self.assertIn('MENÚ MARKETING', html)
        self.assertLess(html.index('FIN MENÚ MARKETING ══ -->'), html.index('Selector de tema integrado en navbar'))
        self.assertLess(html.index('FIN MENÚ MARKETING MÓVIL'), html.index('Selector de tema en móvil'))

    def test_gerente_no_ve_el_menu(self):
        g = User.objects.create_user('ger', 'g@x.com', 'x')
        g.perfil.rol = 'gerente'
        g.perfil.save()
        self.client.force_login(g)
        r = self.client.get(reverse('core:dashboard'), follow=True)
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertNotIn('/marketing/', html)
        self.assertNotIn('📣', html)


class CampanaTests(Base):
    def _datos(self, **kw):
        d = {'marca': self.marca.pk, 'titulo': 'Nueva', 'objetivo': 'captar', 'estado': 'borrador',
             'origen_visual': 'propias', 'quien_escribe': 'ia_editable', 'redes': ['instagram', 'tiktok'],
             'fichas': [self.ficha.pk], 'sucursal_id': '', 'profesional_id': '',
             'lin_publico': 'Madres de Potosí', 'lin_evitar': 'caras de niños'}
        d.update(kw)
        return d

    def test_crear_campana(self):
        r = self.client.post(reverse('marketing:campana_crear'), self._datos())
        c = Campana.objects.get(titulo='Nueva')
        self.assertRedirects(r, reverse('marketing:campana_detalle', args=[c.pk]))
        self.assertEqual(c.redes, ['instagram', 'tiktok'])
        self.assertEqual(c.lineamientos, {'publico': 'Madres de Potosí', 'evitar': 'caras de niños'})
        self.assertEqual(c.creada_por, self.dueno)
        self.assertEqual(list(c.fichas.all()), [self.ficha])

    def test_no_se_mezclan_fichas_de_otra_marca(self):
        kids = Marca.objects.get(slug='misael-kids')
        r = self.client.post(reverse('marketing:campana_crear'), self._datos(marca=kids.pk))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Campana.objects.filter(titulo='Nueva').exists())
        self.assertContains(r, 'otra marca')

    def test_ficha_sin_aprobar_no_es_seleccionable(self):
        otra = FichaContenido.objects.create(marca=self.marca, titulo='Pend', texto='x', aprobada=False)
        r = self.client.post(reverse('marketing:campana_crear'), self._datos(fichas=[otra.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Campana.objects.filter(titulo='Nueva').exists())

    def test_sede_valida_y_invalida(self):
        s = Sucursal.objects.create(nombre='Sede', direccion='x', telefono='1')
        self.client.post(reverse('marketing:campana_crear'), self._datos(sucursal_id=str(s.pk)))
        self.assertEqual(Campana.objects.get(titulo='Nueva').sucursal_id, s.pk)
        r = self.client.post(reverse('marketing:campana_crear'), self._datos(titulo='X2', sucursal_id='99999'))
        self.assertFalse(Campana.objects.filter(titulo='X2').exists())

    def test_editar_conserva_y_actualiza(self):
        r = self.client.post(reverse('marketing:campana_editar', args=[self.campana.pk]),
                             self._datos(titulo='Cambiado', estado='en_curso'))
        self.campana.refresh_from_db()
        self.assertEqual(self.campana.titulo, 'Cambiado')
        self.assertEqual(self.campana.estado, 'en_curso')

    def test_archivar_y_restaurar(self):
        u = reverse('marketing:campana_archivar', args=[self.campana.pk])
        self.client.post(u)
        self.campana.refresh_from_db()
        self.assertEqual(self.campana.estado, 'archivada')
        self.assertNotContains(self.client.get(reverse('marketing:campana_lista')), 'Camp</p>')
        self.client.post(u)
        self.campana.refresh_from_db()
        self.assertEqual(self.campana.estado, 'borrador')


class GuionesVistasTests(Base):
    def test_generar_con_ia_y_aprobar(self):
        prov = ProveedorFalso([guion_json()])
        with mock.patch('marketing.views.obtener_proveedor_texto', return_value=prov):
            r = self.client.post(reverse('marketing:guion_generar', args=[self.campana.pk]),
                                 {'cantidad': '1', 'proveedor': '', 'instrucciones_extra': 'cupos esta semana'},
                                 follow=True)
        g = Guion.objects.get(campana=self.campana)
        self.assertEqual(g.estado, 'validado')
        self.campana.refresh_from_db()
        self.assertEqual(self.campana.estado, 'en_curso')
        self.assertIn('cupos esta semana', prov.prompts[0][1])
        self.assertContains(r, 'Aprobar')
        self.client.post(reverse('marketing:guion_aprobar', args=[g.pk]))
        g.refresh_from_db()
        self.assertEqual(g.estado, 'aprobado')

    def test_generar_sin_proveedor_muestra_error_claro(self):
        with mock.patch.dict(os.environ, {'GEMINI_API_KEY': '', 'GROQ_API_KEY': ''}):
            r = self.client.post(reverse('marketing:guion_generar', args=[self.campana.pk]),
                                 {'cantidad': '1'}, follow=True)
        self.assertContains(r, 'No hay ningún proveedor')
        self.assertFalse(Guion.objects.exists())

    def test_guion_rechazado_muestra_sus_errores_y_no_se_aprueba(self):
        prov = ProveedorFalso([guion_json(caption='cura todo')] * 2)
        with mock.patch('marketing.views.obtener_proveedor_texto', return_value=prov):
            r = self.client.post(reverse('marketing:guion_generar', args=[self.campana.pk]),
                                 {'cantidad': '1'}, follow=True)
        g = Guion.objects.get()
        self.assertEqual(g.estado, 'rechazado')
        self.assertContains(r, 'No pasó la validación')
        self.assertContains(r, 'cura')
        self.client.post(reverse('marketing:guion_aprobar', args=[g.pk]))
        g.refresh_from_db()
        self.assertEqual(g.estado, 'rechazado')

    def test_guion_manual_con_escenas(self):
        r = self.client.post(reverse('marketing:guion_manual', args=[self.campana.pk]), {
            'gancho': 'Hola familias', 'caption': 'Agenda tu evaluación', 'hashtags': '#a #b',
            'texto_pantalla': ['Uno', 'Dos', ''], 'locucion': ['l1', 'l2', ''],
            'prompt_visual': ['v1', 'v2', ''], 'duracion_seg': ['5', '4,5', '4'],
        })
        self.assertRedirects(r, reverse('marketing:campana_detalle', args=[self.campana.pk]))
        g = Guion.objects.get()
        self.assertEqual(g.estado, 'validado')
        self.assertEqual(len(g.escenas), 2)          # la fila vacía se ignora
        self.assertEqual(g.escenas[1]['duracion_seg'], 4.5)
        self.assertEqual(g.generado_por, 'usuario')

    def test_guion_manual_invalido_queda_rechazado(self):
        self.client.post(reverse('marketing:guion_manual', args=[self.campana.pk]), {
            'gancho': 'Resultados garantizados', 'caption': 'x', 'texto_pantalla': ['a'], 'locucion': ['b'],
            'prompt_visual': ['c'], 'duracion_seg': ['5']})
        self.assertEqual(Guion.objects.get().estado, 'rechazado')

    def test_nueva_version_desde_base_precarga_datos(self):
        g = Guion.objects.create(campana=self.campana, version=1, gancho='GANCHO_BASE',
                                 escenas=[{'texto_pantalla': 'T', 'locucion': 'L', 'prompt_visual': 'V', 'duracion_seg': 4}])
        r = self.client.get(reverse('marketing:guion_manual', args=[self.campana.pk]) + f'?base={g.pk}')
        self.assertContains(r, 'GANCHO_BASE')

    def test_no_se_elimina_aprobado_pero_si_borrador(self):
        a = Guion.objects.create(campana=self.campana, version=1, estado='aprobado', gancho='g')
        b = Guion.objects.create(campana=self.campana, version=2, estado='rechazado', gancho='g')
        self.client.post(reverse('marketing:guion_eliminar', args=[a.pk]))
        self.client.post(reverse('marketing:guion_eliminar', args=[b.pk]))
        self.assertTrue(Guion.objects.filter(pk=a.pk).exists())
        self.assertFalse(Guion.objects.filter(pk=b.pk).exists())

    def test_campana_donde_el_usuario_escribe_no_ofrece_ia(self):
        self.campana.quien_escribe = 'usuario'
        self.campana.save()
        r = self.client.get(reverse('marketing:campana_detalle', args=[self.campana.pk]))
        self.assertNotContains(r, 'Generar con IA')
        self.assertContains(r, 'Escribir guion')


class FichasVistasTests(Base):
    def test_editar_texto_quita_aprobacion(self):
        r = self.client.post(reverse('marketing:ficha_editar', args=[self.ficha.pk]), {
            'marca': self.marca.pk, 'tipo': 'servicio', 'titulo': 'Lenguaje', 'texto': 'TEXTO NUEVO', 'activa': 'on'})
        self.ficha.refresh_from_db()
        self.assertEqual(self.ficha.texto, 'TEXTO NUEVO')
        self.assertFalse(self.ficha.aprobada)

    def test_editar_sin_cambiar_texto_conserva_aprobacion(self):
        self.client.post(reverse('marketing:ficha_editar', args=[self.ficha.pk]), {
            'marca': self.marca.pk, 'tipo': 'servicio', 'titulo': 'Otro título', 'texto': self.ficha.texto, 'activa': 'on'})
        self.ficha.refresh_from_db()
        self.assertEqual(self.ficha.titulo, 'Otro título')
        self.assertTrue(self.ficha.aprobada)

    def test_aprobar_y_quitar(self):
        f = FichaContenido.objects.create(marca=self.marca, titulo='P', texto='x')
        u = reverse('marketing:ficha_aprobar', args=[f.pk])
        self.client.post(u); f.refresh_from_db()
        self.assertTrue(f.aprobada); self.assertEqual(f.aprobada_por, self.dueno)
        self.client.post(u); f.refresh_from_db()
        self.assertFalse(f.aprobada); self.assertIsNone(f.aprobada_por)

    def test_next_externo_se_ignora(self):
        r = self.client.post(reverse('marketing:ficha_aprobar', args=[self.ficha.pk]),
                             {'next': 'https://malicioso.com/robar'})
        self.assertRedirects(r, reverse('marketing:ficha_lista'))
        r = self.client.post(reverse('marketing:ficha_aprobar', args=[self.ficha.pk]),
                             {'next': '/marketing/campanas/'})
        self.assertRedirects(r, '/marketing/campanas/')

    def test_crear_ficha_manual_queda_sin_aprobar(self):
        kids = Marca.objects.get(slug='misael-kids')
        self.client.post(reverse('marketing:ficha_crear'), {
            'marca': kids.pk, 'tipo': 'programa', 'titulo': 'Nivel inicial', 'texto': 'Para niños de 3 años', 'activa': 'on'})
        f = FichaContenido.objects.get(titulo='Nivel inicial')
        self.assertFalse(f.aprobada)

    def test_sincronizar_desde_la_ui(self):
        r = self.client.post(reverse('marketing:ficha_sincronizar'), follow=True)
        self.assertContains(r, 'Sincronizado')
        self.assertTrue(FichaContenido.objects.filter(fuente='servicios_data').exists())


class MarcaYConfigTests(Base):
    def test_editar_marca(self):
        datos = {f: getattr(self.marca, f) for f in
                 ['nombre', 'tono_voz', 'lineamientos_base', 'reglas_contenido', 'palabras_prohibidas',
                  'cierre_fijo', 'whatsapp', 'url_web', 'hashtags_base', 'color_primario', 'color_secundario',
                  'color_acento', 'cuenta_facebook', 'cuenta_instagram', 'cuenta_tiktok']}
        datos['whatsapp'] = '76175352'
        datos['color_primario'] = '#1D4ED8'
        r = self.client.post(reverse('marketing:marca_editar', args=[self.marca.pk]), datos)
        self.assertRedirects(r, reverse('marketing:marca_lista'))
        self.marca.refresh_from_db()
        self.assertEqual(self.marca.whatsapp, '76175352')
        self.assertFalse(self.marca.permite_precios)   # no marcado -> False

    def test_color_invalido_se_rechaza(self):
        datos = {'nombre': 'X', 'color_primario': 'azul'}
        r = self.client.post(reverse('marketing:marca_editar', args=[self.marca.pk]), datos)
        self.assertEqual(r.status_code, 200)
        self.marca.refresh_from_db()
        self.assertNotEqual(self.marca.nombre, 'X')

    def test_config(self):
        r = self.client.post(reverse('marketing:config'), {
            'proveedor_texto': '', 'presupuesto_mensual_usd': '35.50', 'tope_por_pieza_usd': '4',
            'calidad_por_defecto': 'final', 'retencion_intermedios_dias': '15'})
        self.assertRedirects(r, reverse('marketing:config'))
        c = ConfigMarketing.get()
        self.assertEqual(str(c.presupuesto_mensual_usd), '35.50')
        self.assertFalse(c.ia_permite_ninos_realistas)

    def test_panel_avisa_si_no_hay_ia(self):
        with mock.patch.dict(os.environ, {'GEMINI_API_KEY': '', 'GROQ_API_KEY': ''}):
            r = self.client.get(reverse('marketing:panel'))
        self.assertContains(r, 'ningún modelo de IA')


class ActivosVistasTests(Base):
    """
    Django fija el storage de un FileField al cargar el modelo, así que aquí se reemplaza
    directamente el storage del campo por uno temporal (nunca se escribe en media/ del proyecto).
    """

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.campo = Activo._meta.get_field('archivo')
        self.set_storage(FileSystemStorage(location=self.tmp, base_url='/m/'))
        self.addCleanup(setattr, self.campo, 'storage', self.campo.storage)

    def set_storage(self, storage):
        patcher = mock.patch.object(self.campo, 'storage', storage)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, **kw):
        d = {'marca': self.marca.pk, 'nombre': 'Fachada', 'tipo': 'imagen', 'origen': 'instalaciones',
             'archivo': png()}
        d.update(kw)
        return self.client.post(reverse('marketing:activo_subir'), d)

    def test_subir_imagen_valida(self):
        r = self._post()
        self.assertRedirects(r, reverse('marketing:activo_lista'))
        a = Activo.objects.get()
        self.assertEqual(a.subido_por, self.dueno)
        self.assertTrue(a.usable_en_publicidad)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, a.archivo.name)))

    def test_extension_incorrecta(self):
        r = self._post(archivo=SimpleUploadedFile('virus.exe', b'MZ', content_type='application/octet-stream'))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Activo.objects.exists())

    def test_falso_png_no_es_imagen(self):
        r = self._post(archivo=SimpleUploadedFile('falso.png', b'esto no es una imagen', content_type='image/png'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'no es una imagen válida')
        self.assertFalse(Activo.objects.exists())

    def test_menores_sin_autorizacion_quedan_bloqueados_en_la_lista(self):
        self._post(nombre='Niños jugando', contiene_menores='on')
        a = Activo.objects.get()
        self.assertTrue(a.contiene_personas)
        self.assertFalse(a.usable_en_publicidad)
        self.assertContains(self.client.get(reverse('marketing:activo_lista')), 'Bloqueado')

    def test_menores_con_autorizacion_sin_referencia_se_rechaza(self):
        r = self._post(contiene_menores='on', autorizacion_confirmada='on')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Activo.objects.exists())

    def test_menores_con_autorizacion_y_referencia_quedan_usables(self):
        self._post(contiene_menores='on', autorizacion_confirmada='on', autorizacion_nota='Carpeta 2026 #14')
        self.assertTrue(Activo.objects.get().usable_en_publicidad)

    def test_produccion_sin_bucket_da_error_claro_sin_caerse(self):
        self.set_storage(MarketingNoConfiguradoStorage(location=self.tmp))
        r = self._post()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'almacenamiento de Marketing no está configurado')
        self.assertFalse(Activo.objects.exists())

    def test_activo_bloqueado_no_aparece_para_campanas(self):
        Activo.objects.create(marca=self.marca, nombre='BLOQ', archivo='x.png', contiene_menores=True, contiene_personas=True)
        Activo.objects.create(marca=self.marca, nombre='LIBRE', archivo='y.png')
        r = self.client.get(reverse('marketing:campana_crear'))
        self.assertContains(r, 'LIBRE')
        self.assertNotContains(r, 'BLOQ')

    def test_toggle(self):
        a = Activo.objects.create(marca=self.marca, nombre='A', archivo='x.png')
        self.client.post(reverse('marketing:activo_toggle', args=[a.pk]))
        a.refresh_from_db()
        self.assertFalse(a.activo)


class AuditoriaVistasTests(Base):
    def test_acciones_quedan_auditadas(self):
        self.client.post(reverse('marketing:ficha_aprobar', args=[self.ficha.pk]))
        self.client.post(reverse('marketing:campana_archivar', args=[self.campana.pk]))
        acciones = set(AuditoriaMarketing.objects.values_list('accion', flat=True))
        self.assertTrue({'ficha_desaprobada', 'campana_estado'} <= acciones)
