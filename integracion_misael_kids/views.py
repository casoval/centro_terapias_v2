"""
integracion_misael_kids/views.py

API de solo lectura consumida por Misael Kids para:
  1. Buscar un paciente para vincularlo con un niño del jardín.
  2. Traer el detalle completo (para copiar datos al crear la ficha).
  3. Listar los documentos que el profesional marcó para compartir
     (planes de trabajo, informes), independientemente de si el
     paciente está activo o inactivo en Centro Misael.

No se expone nada de facturación, agenda clínica ni evaluaciones:
sólo lo estrictamente necesario para el jardín.
"""
from django.db.models import Q
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from documentos.models import DocumentoPaciente
from pacientes.models import Paciente

from .authentication import MisaelKidsAPIKeyAuthentication
from .serializers import (
    DocumentoCompartidoSerializer,
    PacienteBusquedaSerializer,
    PacienteDetalleSerializer,
)


class PacienteBusquedaView(generics.ListAPIView):
    """
    GET /api/integracion/misael-kids/pacientes/buscar/?q=<texto>

    Busca por nombre, apellido o nombre del tutor. Incluye pacientes
    activos e inactivos a propósito: la vinculación con Misael Kids
    no depende del estado del paciente en Centro Misael.
    """
    authentication_classes = [MisaelKidsAPIKeyAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PacienteBusquedaSerializer

    def get_queryset(self):
        q = self.request.query_params.get('q', '').strip()
        qs = Paciente.objects.all().order_by('apellido', 'nombre')
        if q:
            qs = qs.filter(
                Q(nombre__icontains=q) |
                Q(apellido__icontains=q) |
                Q(nombre_tutor__icontains=q)
            )
        return qs[:25]


class PacienteDetalleView(generics.RetrieveAPIView):
    """
    GET /api/integracion/misael-kids/pacientes/<id>/

    Detalle completo para copiar al crear/vincular el Niño y sus
    Tutores en Misael Kids. Se sirve sin filtrar por estado.
    """
    authentication_classes = [MisaelKidsAPIKeyAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PacienteDetalleSerializer
    queryset = Paciente.objects.all()


class DocumentosCompartidosView(generics.ListAPIView):
    """
    GET /api/integracion/misael-kids/pacientes/<id>/documentos/

    Sólo documentos marcados con compartir_misael_kids=True.
    Se sirve sin filtrar por estado del paciente: si un profesional
    subió un plan de trabajo y luego el paciente pasó a inactivo, el
    jardín debe seguir viéndolo.
    """
    authentication_classes = [MisaelKidsAPIKeyAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DocumentoCompartidoSerializer

    def get_queryset(self):
        paciente_id = self.kwargs['paciente_id']
        return (
            DocumentoPaciente.objects
            .filter(paciente_id=paciente_id, compartir_misael_kids=True)
            .select_related('subido_por')
            .order_by('-fecha_subida')
        )


class PingView(APIView):
    """Endpoint trivial para probar la API key desde Misael Kids."""
    authentication_classes = [MisaelKidsAPIKeyAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({'ok': True, 'centro': 'Centro Misael'})
