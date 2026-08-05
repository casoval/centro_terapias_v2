from rest_framework import serializers

from documentos.models import DocumentoPaciente
from pacientes.models import Paciente


class PacienteBusquedaSerializer(serializers.ModelSerializer):
    """Resultado liviano para el buscador de vinculación en Misael Kids."""
    nombre_completo = serializers.CharField(read_only=True)
    edad = serializers.IntegerField(read_only=True)

    class Meta:
        model = Paciente
        fields = [
            'id', 'nombre_completo', 'nombre', 'apellido',
            'fecha_nacimiento', 'edad', 'genero', 'estado',
            'nombre_tutor', 'telefono_tutor',
        ]


class PacienteDetalleSerializer(serializers.ModelSerializer):
    """
    Detalle completo para copiar datos al crear/vincular el niño en
    Misael Kids. Incluye pacientes inactivos: el estado en Centro
    Misael no debe impedir la vinculación ni la copia de datos.
    """
    nombre_completo = serializers.CharField(read_only=True)
    edad = serializers.IntegerField(read_only=True)
    foto_url = serializers.SerializerMethodField()

    class Meta:
        model = Paciente
        fields = [
            'id', 'nombre', 'apellido', 'nombre_completo',
            'fecha_nacimiento', 'edad', 'genero', 'estado',
            'foto_url',
            'nombre_tutor', 'parentesco', 'telefono_tutor', 'email_tutor', 'direccion',
            'nombre_tutor_2', 'parentesco_2', 'telefono_tutor_2', 'email_tutor_2',
            'diagnostico', 'observaciones_medicas', 'alergias',
            'nombre_escuela', 'grado_curso',
        ]

    def get_foto_url(self, obj):
        try:
            return obj.foto.url if obj.foto else None
        except Exception:
            return None


class DocumentoCompartidoSerializer(serializers.ModelSerializer):
    """
    Documentos que el profesional marcó explícitamente como
    "Compartir con Misael Kids" (plan de trabajo, informes, etc).
    """
    archivo_url = serializers.SerializerMethodField()
    subido_por_nombre = serializers.CharField(source='subido_por.get_full_name', read_only=True)
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)

    class Meta:
        model = DocumentoPaciente
        fields = [
            'id', 'paciente_id', 'tipo', 'tipo_display', 'titulo', 'descripcion',
            'archivo_url', 'nombre_archivo', 'extension',
            'subido_por_nombre', 'fecha_subida',
        ]

    def get_archivo_url(self, obj):
        request = self.context.get('request')
        try:
            url = obj.archivo.url
        except Exception:
            return None
        return request.build_absolute_uri(url) if request else url
