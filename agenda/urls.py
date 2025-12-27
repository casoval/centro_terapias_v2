from django.urls import path
from . import views

app_name = 'agenda'

urlpatterns = [
    # Vistas principales
    path('', views.calendario, name='calendario'),
    path('agendar-recurrente/', views.agendar_recurrente, name='agendar_recurrente'),
    
    # ✅ APIs HTMX para cascada de filtros (ORDEN CORRECTO)
    path('api/pacientes-sucursal/', views.cargar_pacientes_sucursal, name='pacientes_sucursal'),
    path('api/servicios-paciente/', views.cargar_servicios_paciente, name='servicios_paciente'),
    path('api/profesionales-servicio/', views.cargar_profesionales_por_servicio, name='profesionales_servicio'),
    
    # 🆕 NUEVO: API para cargar proyectos del paciente
    path('api/proyectos-paciente/<int:paciente_id>/', views.obtener_proyectos_paciente, name='proyectos_paciente'),
    
    # Otras APIs
    path('api/vista-previa/', views.vista_previa_recurrente, name='vista_previa'),
    path('api/editar/<int:sesion_id>/', views.editar_sesion, name='editar_sesion'),
    path('api/validar-horario/', views.validar_horario, name='validar_horario'),
    
    # 🆕 NUEVO: Modal de confirmación de cambio de estado
    path('api/modal-confirmar-estado/<int:sesion_id>/', 
         views.modal_confirmar_cambio_estado, 
         name='modal_confirmar_estado'),
    
    # 🆕 PROYECTOS
    path('proyectos/', views.lista_proyectos, name='lista_proyectos'),
    path('proyectos/crear/', views.crear_proyecto, name='crear_proyecto'),
    path('proyectos/<int:proyecto_id>/', views.detalle_proyecto, name='detalle_proyecto'),
    path('proyectos/<int:proyecto_id>/actualizar-estado/', views.actualizar_estado_proyecto, name='actualizar_estado_proyecto'),

    # 🆕 Procesar cambio de estado con confirmación
    path('sesion/<int:sesion_id>/procesar-cambio-estado/', 
         views.procesar_cambio_estado, 
         name='procesar_cambio_estado'),

    path('confirmacion-sesiones/', views.confirmacion_sesiones, name='confirmacion_sesiones'),
]