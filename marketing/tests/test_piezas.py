import io
import shutil
import tempfile
from types import SimpleNamespace as NS
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from PIL import Image

from marketing import render_imagenes as ri
from marketing.models import (
    Activo, AuditoriaMarketing, Campana, Elemento, FichaContenido, Guion, Marca, Pieza, Publicacion,
)
from marketing.piezas import (
    PiezaError, actualizar_textos, aprobar_pieza, crear_pieza, generar_pieza, paquete_descarga,
    preparar_publicacion, registrar_publicada,
)

MARCA = NS(nombre='Centro Misael', color_primario='#7C3AED', color_secundario='#DB2777', color_acento='#FBBF24',
           whatsapp='+591 70000000', url_web='https://centromisael.com', cuenta_instagram='centromisael',
           cuenta_facebook='', cuenta_tiktok='')


class RenderTests(SimpleTestCase):
    def test_tamanos_y_roles(self):
        for ancho, alto in [(1080, 1350), (1080, 1080), (1080, 1920)]:
            for rol in ri.ROLES:
                img = ri.renderizar(MARCA, rol, 'Terapia de lenguaje para niños', ancho=ancho, alto=alto, indice=2, total=4)
                self.assertEqual(img.size, (ancho, alto))
                self.assertEqual(img.mode, 'RGB')

    def test_rol_invalido(self):
        with self.assertRaises(ValueError):
            ri.renderizar(MARCA, 'otro', 'x', ancho=100, alto=100)

    def test_con_foto_y_logo(self):
        foto = Image.new('RGB', (1600, 900), 'orange')
        logo = Image.new('RGBA', (300, 100), (10, 20, 30, 255))
        img = ri.renderizar(MARCA, 'portada', 'Hola', ancho=1080, alto=1350, foto=foto, logo=logo, total=3)
        self.assertEqual(img.size, (1080, 1350))

    def test_texto_muy_largo_y_palabra_enorme_no_revientan(self):
        largo = 'palabra ' * 120
        ri.renderizar(MARCA, 'contenido', largo, ancho=1080, alto=1350)
        ri.renderizar(MARCA, 'portada', 'a' * 400, ancho=1080, alto=1350)

    def test_marca_sin_colores_usa_los_de_respaldo(self):
        vacia = NS(nombre='X', color_primario='', color_secundario='zz', color_acento=None)
        self.assertEqual(ri.renderizar(vacia, 'cierre', 'Hola', ancho=540, alto=960).size, (540, 960))

    def test_contraste_elige_color_legible(self):
        self.assertEqual(ri.color_texto_sobre((255, 255, 255)), ri.TINTA)
        self.assertEqual(ri.color_texto_sobre((10, 10, 40)), ri.BLANCO)

    def test_jpeg_y_miniatura(self):
        img = ri.renderizar(MARCA, 'portada', 'Hola', ancho=1080, alto=1350)
        datos = ri.a_jpeg(img)
        self.assertEqual(Image.open(io.BytesIO(datos)).format, 'JPEG')
        self.assertLessEqual(ri.miniatura(img).width, 480)


class Base(TestCase):
    def setUp(self):
        call_command('cargar_marcas_iniciales', verbosity=0)
        self.dueno = User.objects.create_superuser('dueno', 'd@x.com', 'x')
        self.marca = Marca.objects.get(slug='centro-misael')
        self.marca.whatsapp = '+591 70000000'
        self.marca.cierre_fijo = 'Agenda tu evaluación por WhatsApp'
        self.marca.save()
        ficha = FichaContenido.objects.create(
            marca=self.marca, titulo='Lenguaje', texto='SERVICIO: Terapia de lenguaje.', aprobada=True)
        self.campana = Campana.objects.create(
            marca=self.marca, titulo='Camp', redes=['instagram', 'facebook'], origen_visual='propias')
        self.campana.fichas.add(ficha)
        self.guion = Guion.objects.create(
            campana=self.campana, version=1, estado='aprobado', gancho='¿Tu hijo necesita apoyo para hablar?',
            escenas=[
                {'texto_pantalla': 'Terapia de lenguaje', 'locucion': 'a', 'prompt_visual': 'x', 'duracion_seg': 4},
                {'texto_pantalla': '', 'locucion': 'solo voz', 'prompt_visual': 'y', 'duracion_seg': 4},
                {'texto_pantalla': 'Agenda tu evaluación', 'locucion': 'b', 'prompt_visual': 'z', 'duracion_seg': 4},
            ],
            caption='Agenda tu evaluación por WhatsApp.', hashtags='#potosi #terapia',
        )
        # Todos los FileField de marketing escriben en una carpeta temporal.
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        almacen = FileSystemStorage(location=self.tmp, base_url='/m/')
        for modelo, campo in [(Elemento, 'archivo'), (Pieza, 'miniatura'), (Pieza, 'archivo_final'),
                              (Activo, 'archivo'), (Marca, 'logo')]:
            patcher = mock.patch.object(modelo._meta.get_field(campo), 'storage', almacen)
            patcher.start()
            self.addCleanup(patcher.stop)

    def foto(self, autorizada=True, menores=False, nombre='Foto'):
        buf = io.BytesIO()
        Image.new('RGB', (800, 600), 'teal').save(buf, 'JPEG')
        return Activo.objects.create(
            marca=self.marca, nombre=nombre, tipo='imagen', origen='instalaciones',
            archivo=SimpleUploadedFile(f'{nombre}.jpg', buf.getvalue(), content_type='image/jpeg'),
            contiene_personas=True, contiene_menores=menores, autorizacion_confirmada=autorizada,
            autorizacion_nota='Carpeta 2026, ficha 3' if autorizada else '',
        )


class CrearPiezaTests(Base):
    def test_carrusel_portada_escenas_con_texto_y_cierre(self):
        pieza, _ = crear_pieza(self.campana, self.guion, 'carrusel', '4x5', self.dueno)
        textos = [e.texto_pantalla for e in pieza.elementos.order_by('orden')]
        self.assertEqual(textos, ['¿Tu hijo necesita apoyo para hablar?', 'Terapia de lenguaje',
                                  'Agenda tu evaluación', 'Agenda tu evaluación por WhatsApp'])
        self.assertEqual(pieza.datos_trabajo['roles'], ['portada', 'contenido', 'contenido', 'cierre'])

    def test_imagen_unica(self):
        pieza, _ = crear_pieza(self.campana, self.guion, 'imagen', '1x1', self.dueno)
        self.assertEqual(pieza.elementos.count(), 1)

    def test_exige_guion_aprobado(self):
        self.guion.estado = 'validado'
        self.guion.save()
        with self.assertRaises(PiezaError):
            crear_pieza(self.campana, self.guion, 'carrusel', '4x5')

    def test_rechaza_video_y_formato_horizontal(self):
        with self.assertRaises(PiezaError):
            crear_pieza(self.campana, self.guion, 'video', '9x16')
        with self.assertRaises(PiezaError):
            crear_pieza(self.campana, self.guion, 'carrusel', '16x9')

    def test_demasiadas_diapositivas(self):
        self.guion.escenas = [{'texto_pantalla': f'Escena {i}', 'duracion_seg': 4} for i in range(10)]
        self.guion.save()
        with self.assertRaises(PiezaError):
            crear_pieza(self.campana, self.guion, 'carrusel', '4x5')

    def test_guion_de_otra_campana(self):
        otra = Campana.objects.create(marca=self.marca, titulo='Otra')
        with self.assertRaises(PiezaError):
            crear_pieza(otra, self.guion, 'carrusel', '4x5')

    def test_fotos_sin_autorizacion_no_se_usan_y_se_avisa(self):
        buena, mala = self.foto(True, nombre='Buena'), self.foto(False, menores=True, nombre='Mala')
        self.campana.activos_referencia.add(buena, mala)
        pieza, avisos = crear_pieza(self.campana, self.guion, 'carrusel', '4x5')
        usados = {e.activo_referencia_id for e in pieza.elementos.all()} - {None}
        self.assertEqual(usados, {buena.pk})
        self.assertTrue(any('autorización' in a for a in avisos))
        self.assertIsNone(pieza.elementos.get(orden=4).activo_referencia)  # el cierre no lleva foto

    def test_ia_total_no_usa_fotos(self):
        self.campana.origen_visual = 'ia_total'
        self.campana.save()
        self.campana.activos_referencia.add(self.foto())
        pieza, _ = crear_pieza(self.campana, self.guion, 'carrusel', '4x5')
        self.assertFalse(pieza.elementos.exclude(activo_referencia=None).exists())


class GenerarYAprobarTests(Base):
    def crear(self, tipo='carrusel'):
        pieza, _ = crear_pieza(self.campana, self.guion, tipo, '4x5', self.dueno)
        return generar_pieza(pieza)

    def test_genera_imagenes_reales(self):
        self.campana.activos_referencia.add(self.foto())
        pieza = self.crear()
        self.assertEqual(pieza.estado, 'listo')
        for e in pieza.elementos.all():
            self.assertEqual(e.estado, 'listo')
            with e.archivo.open('rb') as f:
                self.assertEqual(Image.open(f).size, (1080, 1350))
        self.assertTrue(pieza.miniatura)

    def test_imagen_unica_guarda_archivo_final(self):
        self.assertTrue(self.crear('imagen').archivo_final)

    def test_falla_con_motivo_si_la_foto_perdio_autorizacion(self):
        foto = self.foto()
        self.campana.activos_referencia.add(foto)
        pieza, _ = crear_pieza(self.campana, self.guion, 'carrusel', '4x5')
        foto.autorizacion_confirmada = False
        foto.save()
        generar_pieza(pieza)
        self.assertEqual(pieza.estado, 'fallida')
        self.assertIn('autorización', pieza.error)

    def test_aprobar(self):
        pieza = self.crear()
        aprobar_pieza(pieza, self.dueno)
        pieza.refresh_from_db()
        self.assertEqual((pieza.estado, pieza.aprobada_por), ('aprobado', self.dueno))
        self.assertTrue(AuditoriaMarketing.objects.filter(accion='pieza_aprobada').exists())

    def test_no_aprueba_si_el_guion_ya_no_esta_aprobado(self):
        pieza = self.crear()
        self.guion.estado = 'validado'
        self.guion.save()
        with self.assertRaises(PiezaError):
            aprobar_pieza(pieza, self.dueno)

    def test_no_aprueba_si_cambio_una_regla_de_la_marca(self):
        pieza = self.crear()
        self.marca.palabras_prohibidas = 'apoyo'
        self.marca.save()
        with self.assertRaises(PiezaError):
            aprobar_pieza(pieza, self.dueno)

    def test_no_aprueba_si_la_foto_perdio_autorizacion(self):
        foto = self.foto()
        self.campana.activos_referencia.add(foto)
        pieza = self.crear()
        foto.autorizacion_confirmada = False
        foto.save()
        with self.assertRaises(PiezaError):
            aprobar_pieza(pieza, self.dueno)

    def test_editar_texto_redibuja_solo_lo_cambiado_y_quita_aprobacion(self):
        pieza = self.crear()
        aprobar_pieza(pieza, self.dueno)
        el = pieza.elementos.get(orden=2)
        otro = pieza.elementos.get(orden=3)
        nombre_otro = otro.archivo.name
        with el.archivo.open('rb') as f:
            antes = f.read()
        _, n = actualizar_textos(pieza, {el.pk: 'Evaluación sin presión'}, self.dueno)
        self.assertEqual(n, 1)
        pieza.refresh_from_db(); el.refresh_from_db(); otro.refresh_from_db()
        self.assertEqual(el.texto_pantalla, 'Evaluación sin presión')
        with el.archivo.open('rb') as f:
            self.assertNotEqual(f.read(), antes)  # la imagen cambió
        self.assertEqual(otro.archivo.name, nombre_otro)
        self.assertEqual(pieza.estado, 'listo')
        self.assertIsNone(pieza.aprobada_por)

    def test_editar_con_palabra_prohibida_se_rechaza_y_no_guarda(self):
        self.marca.palabras_prohibidas = 'cura'
        self.marca.save()
        pieza = self.crear()
        el = pieza.elementos.get(orden=2)
        with self.assertRaises(PiezaError):
            actualizar_textos(pieza, {el.pk: 'La cura para tu hijo'})
        el.refresh_from_db()
        self.assertEqual(el.texto_pantalla, 'Terapia de lenguaje')

    def test_editar_sin_texto_o_sin_cambios(self):
        pieza = self.crear()
        el = pieza.elementos.get(orden=2)
        with self.assertRaises(PiezaError):
            actualizar_textos(pieza, {el.pk: '   '})
        self.assertEqual(actualizar_textos(pieza, {el.pk: el.texto_pantalla})[1], 0)

    def test_precio_en_el_cierre_se_rechaza(self):
        pieza = self.crear()
        cierre = pieza.elementos.get(orden=4)
        with self.assertRaises(PiezaError):
            actualizar_textos(pieza, {cierre.pk: 'Consulta a solo 50 bolivianos'})

    def test_descarga_zip_y_jpg(self):
        import zipfile
        nombre, datos, mime = paquete_descarga(self.crear())
        self.assertEqual((nombre.endswith('.zip'), mime), (True, 'application/zip'))
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            nombres = z.namelist()
        self.assertEqual(len([n for n in nombres if n.endswith('.jpg')]), 4)
        self.assertTrue(any(n.endswith('_texto.txt') for n in nombres))
        nombre, datos, mime = paquete_descarga(self.crear('imagen'))
        self.assertEqual((nombre.endswith('.jpg'), mime), (True, 'image/jpeg'))

    def test_publicacion_manual(self):
        pieza = self.crear()
        with self.assertRaises(PiezaError):
            preparar_publicacion(pieza, 'instagram')  # sin aprobar
        aprobar_pieza(pieza, self.dueno)
        pub, nueva = preparar_publicacion(pieza, 'instagram', self.dueno)
        self.assertTrue(nueva)
        self.assertEqual(pub.caption, self.guion.caption)
        self.assertFalse(preparar_publicacion(pieza, 'instagram')[1])
        with self.assertRaises(PiezaError):
            preparar_publicacion(pieza, 'myspace')
        registrar_publicada(pub, self.dueno, url='https://instagram.com/p/x', etiqueta_ia=True)
        pieza.refresh_from_db(); pub.refresh_from_db()
        self.assertEqual((pieza.estado, pub.estado, pub.etiqueta_ia_activada), ('publicada', 'publicada', True))
        with self.assertRaises(PiezaError):
            registrar_publicada(pub, self.dueno)


class VistasPiezasTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.dueno)

    def test_flujo_completo_por_pantalla(self):
        r = self.client.post(reverse('marketing:pieza_crear', args=[self.guion.pk]), {'tipo': 'carrusel', 'formato': '4x5'})
        pieza = Pieza.objects.get()
        self.assertRedirects(r, reverse('marketing:pieza_detalle', args=[pieza.pk]))
        self.assertEqual(pieza.estado, 'listo')
        self.assertEqual(self.client.get(reverse('marketing:pieza_detalle', args=[pieza.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('marketing:pieza_lista')).status_code, 200)
        self.assertContains(self.client.get(reverse('marketing:campana_detalle', args=[self.campana.pk])), 'Piezas (1)')

        el = pieza.elementos.get(orden=2)
        self.client.post(reverse('marketing:pieza_textos', args=[pieza.pk]), {f'texto_{el.pk}': 'Texto nuevo'})
        el.refresh_from_db()
        self.assertEqual(el.texto_pantalla, 'Texto nuevo')

        self.client.post(reverse('marketing:pieza_aprobar', args=[pieza.pk]))
        pieza.refresh_from_db()
        self.assertEqual(pieza.estado, 'aprobado')

        d = self.client.get(reverse('marketing:pieza_descargar', args=[pieza.pk]))
        self.assertEqual((d.status_code, d['Content-Type']), (200, 'application/zip'))

        self.client.post(reverse('marketing:publicacion_crear', args=[pieza.pk]), {'red': 'instagram'})
        pub = Publicacion.objects.get()
        self.client.post(reverse('marketing:publicacion_accion', args=[pub.pk]),
                         {'accion': 'guardar', 'caption': 'Nuevo texto', 'hashtags': '#a #b'})
        pub.refresh_from_db()
        self.assertEqual(pub.caption, 'Nuevo texto')
        self.client.post(reverse('marketing:publicacion_accion', args=[pub.pk]),
                         {'accion': 'publicar', 'url_publica': 'https://instagram.com/p/1', 'etiqueta_ia': 'on'})
        pieza.refresh_from_db(); pub.refresh_from_db()
        self.assertEqual((pieza.estado, pub.estado), ('publicada', 'publicada'))
        self.assertEqual(self.client.get(reverse('marketing:pieza_detalle', args=[pieza.pk])).status_code, 200)

    def test_publicacion_con_precio_en_el_texto_se_rechaza(self):
        pieza, _ = crear_pieza(self.campana, self.guion, 'carrusel', '4x5')
        generar_pieza(pieza)
        aprobar_pieza(pieza, self.dueno)
        pub, _ = preparar_publicacion(pieza, 'facebook')
        self.client.post(reverse('marketing:publicacion_accion', args=[pub.pk]),
                         {'accion': 'guardar', 'caption': 'Solo 100 bolivianos', 'hashtags': ''})
        pub.refresh_from_db()
        self.assertEqual(pub.caption, self.guion.caption)

    def test_guion_sin_aprobar_no_crea_pieza(self):
        self.guion.estado = 'validado'
        self.guion.save()
        self.client.post(reverse('marketing:pieza_crear', args=[self.guion.pk]), {'tipo': 'carrusel', 'formato': '4x5'})
        self.assertFalse(Pieza.objects.exists())

    def test_eliminar(self):
        self.client.post(reverse('marketing:pieza_crear', args=[self.guion.pk]), {'tipo': 'imagen', 'formato': '1x1'})
        pieza = Pieza.objects.get()
        self.client.post(reverse('marketing:pieza_eliminar', args=[pieza.pk]))
        self.assertFalse(Pieza.objects.exists())

    def test_descarga_requiere_pieza_lista(self):
        pieza = Pieza.objects.create(campana=self.campana, guion=self.guion, estado='pendiente')
        r = self.client.get(reverse('marketing:pieza_descargar', args=[pieza.pk]))
        self.assertEqual(r.status_code, 302)

    def test_solo_superusuario_y_solo_post(self):
        pieza = Pieza.objects.create(campana=self.campana, guion=self.guion, estado='listo')
        normal = User.objects.create_user('otro', 'o@x.com', 'x', is_staff=True)
        self.client.force_login(normal)
        for nombre in ('pieza_detalle', 'pieza_descargar'):
            self.assertEqual(self.client.get(reverse(f'marketing:{nombre}', args=[pieza.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('marketing:pieza_lista')).status_code, 403)
        self.client.force_login(self.dueno)
        for nombre in ('pieza_aprobar', 'pieza_eliminar', 'pieza_regenerar', 'pieza_textos'):
            self.assertEqual(self.client.get(reverse(f'marketing:{nombre}', args=[pieza.pk])).status_code, 405)

    def test_panel_reconoce_cloudinary(self):
        from django.test import override_settings
        with override_settings(MARKETING_R2_CONFIGURADO=False, MARKETING_STORAGE_BACKEND='cloudinary',
                               MARKETING_CLOUDINARY_CONFIGURADO=True,
                               MARKETING_CLOUDINARY={'cloud_name': 'a', 'api_key': 'b', 'api_secret': 'c'},
                               IS_PRODUCTION=True):
            r = self.client.get(reverse('marketing:panel'))
        self.assertNotContains(r, 'almacenamiento de Marketing no está configurado')
