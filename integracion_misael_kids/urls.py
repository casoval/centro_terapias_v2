from django.urls import path

from .views import DocumentosCompartidosView, PacienteBusquedaView, PacienteDetalleView, PingView

app_name = 'integracion_misael_kids'

urlpatterns = [
    path('ping/', PingView.as_view(), name='ping'),
    path('pacientes/buscar/', PacienteBusquedaView.as_view(), name='pacientes-buscar'),
    path('pacientes/<int:pk>/', PacienteDetalleView.as_view(), name='pacientes-detalle'),
    path('pacientes/<int:paciente_id>/documentos/', DocumentosCompartidosView.as_view(), name='pacientes-documentos'),
]
