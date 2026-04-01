from django.urls import path
from . import views

app_name = 'agenda'

urlpatterns = [
    # Vistas principales
    path('', views.calendario, name='calendario'),
    path('agendar-recurrente/', views.agendar_recurrente, name='agendar_recurrente'),
    
    # APIs HTMX para cascada de filtros (ORDEN CORRECTO)
    path('api/pacientes-sucursal/', views.cargar_pacientes_sucursal, name='pacientes_sucursal'),
    path('api/servicios-paciente/', views.cargar_servicios_paciente, name='servicios_paciente'),
    path('api/profesionales-servicio/', views.cargar_profesionales_por_servicio, name='profesionales_servicio'),
    
    # API para cargar proyectos del paciente
    path('api/proyectos-paciente/<int:paciente_id>/', views.obtener_proyectos_paciente, name='proyectos_paciente'),
    
    # API para datos de confirmación al cancelar
    path('api/datos-confirmacion-cancelacion/', views.api_datos_confirmacion_cancelacion, name='api_datos_confirmacion_cancelacion'),
    
    # Otras APIs
    path('api/vista-previa/', views.vista_previa_recurrente, name='vista_previa'),
    path('api/editar/<int:sesion_id>/', views.editar_sesion, name='editar_sesion'),
    path('api/eliminar/<int:sesion_id>/', views.eliminar_sesion, name='eliminar_sesion'),
    path('api/validar-horario/', views.validar_horario, name='validar_horario'),

    # Modal de confirmación de cambio de estado
    path('api/modal-confirmar-estado/<int:sesion_id>/', 
         views.modal_confirmar_cambio_estado, 
         name='modal_confirmar_estado'),
    
    # PROYECTOS
    path('proyectos/', views.lista_proyectos, name='lista_proyectos'),
    path('proyectos/crear/', views.crear_proyecto, name='crear_proyecto'),
    path('proyectos/<int:proyecto_id>/', views.detalle_proyecto, name='detalle_proyecto'),
    path('proyectos/<int:proyecto_id>/actualizar-estado/', views.actualizar_estado_proyecto, name='actualizar_estado_proyecto'),
    path('proyectos/<int:proyecto_id>/marcar-informe/', views.marcar_entrega_informe, name='marcar_entrega_informe'),

    # MENSUALIDADES
    path('mensualidades/', views.lista_mensualidades, name='lista_mensualidades'),
    path('mensualidades/crear/', views.crear_mensualidad, name='crear_mensualidad'),
    path('mensualidades/<int:mensualidad_id>/', views.detalle_mensualidad, name='detalle_mensualidad'),
    path('mensualidades/<int:mensualidad_id>/actualizar-estado/', 
         views.actualizar_estado_mensualidad, 
         name='actualizar_estado_mensualidad'),
    path('confirmacion-mensualidad/', views.confirmacion_mensualidad, name='confirmacion_mensualidad'), 
    path('api/mensualidades-paciente/', views.obtener_mensualidades_paciente, name='mensualidades_paciente'),
    
    # Agendamiento rápido desde mensualidad
    path('mensualidades/agendar/modal/<int:servicio_profesional_id>/', 
         views.modal_agendar_mensualidad, 
         name='modal_agendar_mensualidad'),
    path('mensualidades/agendar/procesar/<int:servicio_profesional_id>/', 
         views.procesar_agendar_mensualidad, 
         name='procesar_agendar_mensualidad'),
    path('api/vista-previa-mensualidad/', 
         views.vista_previa_mensualidad, 
         name='vista_previa_mensualidad'),
    
    # Procesar cambio de estado con confirmación
    path('sesion/<int:sesion_id>/procesar-cambio-estado/', 
         views.procesar_cambio_estado, 
         name='procesar_cambio_estado'),

    path('confirmacion-sesiones/', views.confirmacion_sesiones, name='confirmacion_sesiones'),

    # Agregar servicio a mensualidad existente
    path('mensualidades/<int:mensualidad_id>/agregar-servicio/',
         views.agregar_servicio_mensualidad,
         name='agregar_servicio_mensualidad'),
    path('api/servicios-disponibles-mensualidad/',
         views.api_servicios_disponibles_mensualidad,
         name='api_servicios_disponibles_mensualidad'),

    # Copiar mensualidad al mes siguiente
    path('mensualidades/<int:mensualidad_id>/copiar/modal/',
         views.modal_copiar_mensualidad,
         name='modal_copiar_mensualidad'),
    path('mensualidades/<int:mensualidad_id>/copiar/procesar/',
         views.procesar_copiar_mensualidad,
         name='procesar_copiar_mensualidad'),

    # ✅ NUEVO: Agendar por patrón semanal (APIs primero, luego la vista principal)
    path('patron-semanal/api/vinculos-paciente/',
         views.api_vinculos_paciente,
         name='api_vinculos_paciente'),
    path('patron-semanal/api/pacientes-json/',
         views.api_pacientes_sucursal_json,
         name='api_pacientes_sucursal_json'),
    path('patron-semanal/api/semanas-paciente/<int:paciente_id>/',
         views.api_semanas_paciente,
         name='api_semanas_paciente'),
    path('patron-semanal/api/semanas-mes/',
         views.api_semanas_mes,
         name='api_semanas_mes'),
    path('patron-semanal/api/preview/',
         views.api_preview_patron,
         name='api_preview_patron'),
    path('patron-semanal/procesar/',
         views.procesar_patron_semanal,
         name='procesar_patron_semanal'),
    path('patron-semanal/',
         views.agendar_patron_semanal,
         name='agendar_patron_semanal'),

    # INFORME DE EVOLUCIÓN
    path('informe-evolucion/<int:paciente_id>/', 
         views.informe_evolucion, 
         name='informe_evolucion'),
    path('informe-evolucion/<int:paciente_id>/pdf/', 
         views.generar_pdf_informe_evolucion, 
         name='pdf_informe_evolucion'),

    # INFORMES DE EVOLUCIÓN — ROL PROFESIONAL
    path('mis-informes-evolucion/',
         views.mis_informes_evolucion,
         name='mis_informes_evolucion'),
    path('mis-informes-evolucion/<int:paciente_id>/',
         views.informe_evolucion_profesional,
         name='informe_evolucion_profesional'),
    path('mis-informes-evolucion/<int:paciente_id>/pdf/',
         views.generar_pdf_informe_evolucion_profesional,
         name='pdf_informe_evolucion_profesional'),

    # PERMISOS DE EDICIÓN (solo administradores)
    path('permisos-edicion/',
         views.lista_permisos_edicion,
         name='lista_permisos_edicion'),
    path('permisos-edicion/crear/',
         views.crear_permiso_edicion,
         name='crear_permiso_edicion'),
    path('permisos-edicion/<int:permiso_id>/editar/',
         views.editar_permiso_edicion,
         name='editar_permiso_edicion'),
    path('permisos-edicion/<int:permiso_id>/revocar/',
         views.revocar_permiso_edicion,
         name='revocar_permiso_edicion'),

    path('mi-calendario/<int:paciente_id>/', views.mi_calendario_magico, name='mi_calendario_magico'),
    path('guardar-tema-calendario/', views.guardar_tema_calendario, name='guardar_tema_calendario'),
    path('sesiones-sucursal/', views.sesiones_sucursal_profesional, name='sesiones_sucursal_profesional'),
]