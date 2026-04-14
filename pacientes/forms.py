from django import forms
from django.core.exceptions import ValidationError
from .models import Paciente, PacienteServicio
from servicios.models import TipoServicio, Sucursal
from datetime import date


class PacienteForm(forms.ModelForm):
    """
    Formulario personalizado para crear/editar pacientes
    ✅ CON FILTRADO DE SUCURSALES SEGÚN ROL DEL USUARIO
    ✅ SIN procesamiento de servicios (se hace en la vista)
    ✅ CON SECCIÓN DE INFORMACIÓN EDUCATIVA (OPCIONAL)
    """
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # ✅ FILTRADO DE SUCURSALES SEGÚN ROL DEL USUARIO
        if user:
            if user.is_superuser:
                self.fields['sucursales'].queryset = Sucursal.objects.filter(activa=True).order_by('nombre')
            elif hasattr(user, 'perfil'):
                if user.perfil.es_gerente():
                    self.fields['sucursales'].queryset = Sucursal.objects.filter(activa=True).order_by('nombre')
                elif user.perfil.es_recepcionista():
                    mis_sucursales = user.perfil.sucursales.filter(activa=True)
                    self.fields['sucursales'].queryset = mis_sucursales.order_by('nombre')
                    if not mis_sucursales.exists():
                        self.fields['sucursales'].help_text = '⚠️ No tienes sucursales asignadas. Contacta al administrador.'
                else:
                    self.fields['sucursales'].queryset = Sucursal.objects.none()
            else:
                self.fields['sucursales'].queryset = Sucursal.objects.none()
        else:
            self.fields['sucursales'].queryset = Sucursal.objects.filter(activa=True).order_by('nombre')
        
        from core.models import PerfilUsuario
        from django.contrib.auth.models import User

        usuarios_base = User.objects.filter(
            perfil__rol='paciente',
            perfil__isnull=False
        ).exclude(is_superuser=True)

        if self.instance and self.instance.pk and self.instance.user_id:
            usuarios_disponibles = usuarios_base.filter(
                paciente__isnull=True
            ) | usuarios_base.filter(
                id=self.instance.user_id
            )
        else:
            usuarios_disponibles = usuarios_base.filter(
                paciente__isnull=True
            )
        
        self.fields['user'].queryset = usuarios_disponibles.distinct()
        
        def label_usuario(obj):
            try:
                if hasattr(obj, 'paciente') and obj.paciente:
                    return f"{obj.username} - {obj.paciente.nombre_completo} (Vinculado)"
            except:
                pass
            return f"{obj.username} - {obj.get_full_name() or 'Disponible'}"
        
        self.fields['user'].label_from_instance = label_usuario
            
    class Meta:
        model = Paciente
        fields = [
            # Sucursales
            'sucursales',
            # Usuario del sistema
            'user',
            # Foto
            'foto',
            # Info del paciente
            'nombre',
            'apellido',
            'fecha_nacimiento',
            'genero',
            # Tutor principal
            'nombre_tutor',
            'parentesco',
            'telefono_tutor',
            'email_tutor',
            'direccion',
            # Segundo tutor
            'nombre_tutor_2',
            'parentesco_2',
            'telefono_tutor_2',
            'email_tutor_2',
            # Info clínica
            'diagnostico',
            'observaciones_medicas',
            'alergias',
            # ✅ Información educativa
            'nombre_escuela',
            'grado_curso',
            'turno_escolar',
            'nombre_maestro',
            'telefono_escuela',
            'email_escuela',
            'direccion_escuela',
            'apoyo_escolar',
            'observaciones_escuela',
            # Estado
            'estado',
        ]
        
        widgets = {
            'sucursales': forms.CheckboxSelectMultiple(attrs={
                'class': 'space-y-2'
            }),
            'user': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border-2 border-indigo-200 rounded-xl text-sm font-bold',
                'id': 'id_user'
            }),
            'foto': forms.FileInput(attrs={
                'class': 'block w-full text-sm text-gray-900 border border-gray-300 rounded-lg cursor-pointer bg-gray-50 focus:outline-none',
                'accept': 'image/*',
                'id': 'foto-input'
            }),
            'nombre': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-400 focus:border-blue-400 font-bold',
                'placeholder': 'Ej: Juan'
            }),
            'apellido': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-400 focus:border-blue-400 font-bold',
                'placeholder': 'Ej: Pérez'
            }),
            'fecha_nacimiento': forms.DateInput(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-400 focus:border-blue-400 font-bold',
                'type': 'date'
            }),
            'genero': forms.Select(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-400 focus:border-blue-400 font-bold'
            }),
            'nombre_tutor': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-purple-400 focus:border-purple-400 font-bold',
                'placeholder': 'Ej: María González'
            }),
            'parentesco': forms.Select(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-purple-400 focus:border-purple-400 font-bold'
            }),
            'telefono_tutor': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-purple-400 focus:border-purple-400 font-bold',
                'placeholder': 'Ej: 70123456'
            }),
            'email_tutor': forms.EmailInput(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-purple-400 focus:border-purple-400 font-bold',
                'placeholder': 'email@ejemplo.com'
            }),
            'direccion': forms.Textarea(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-purple-400 focus:border-purple-400 font-bold',
                'placeholder': 'Dirección completa...',
                'rows': 2
            }),
            'nombre_tutor_2': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-green-400 focus:border-green-400 font-bold',
                'placeholder': 'Ej: Pedro López (opcional)'
            }),
            'parentesco_2': forms.Select(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-green-400 focus:border-green-400 font-bold'
            }),
            'telefono_tutor_2': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-green-400 focus:border-green-400 font-bold',
                'placeholder': 'Ej: 71234567 (opcional)'
            }),
            'email_tutor_2': forms.EmailInput(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-green-400 focus:border-green-400 font-bold',
                'placeholder': 'email@ejemplo.com (opcional)'
            }),
            'diagnostico': forms.Textarea(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-red-400 focus:border-red-400 font-bold',
                'placeholder': 'Diagnóstico o motivo de consulta...',
                'rows': 3
            }),
            'observaciones_medicas': forms.Textarea(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-red-400 focus:border-red-400 font-bold',
                'placeholder': 'Observaciones médicas relevantes...',
                'rows': 3
            }),
            'alergias': forms.Textarea(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-red-400 focus:border-red-400 font-bold',
                'placeholder': 'Alergias conocidas...',
                'rows': 2
            }),
            # ✅ Widgets para Información Educativa
            'nombre_escuela': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-yellow-400 focus:border-yellow-400 font-bold',
                'placeholder': 'Ej: Unidad Educativa San Calixto'
            }),
            'grado_curso': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-yellow-400 focus:border-yellow-400 font-bold',
                'placeholder': 'Ej: 3° de Primaria, Kínder, Inicial 2'
            }),
            'turno_escolar': forms.Select(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-yellow-400 focus:border-yellow-400 font-bold'
            }),
            'nombre_maestro': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-yellow-400 focus:border-yellow-400 font-bold',
                'placeholder': 'Ej: Prof. Ana Mamani'
            }),
            'telefono_escuela': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-yellow-400 focus:border-yellow-400 font-bold',
                'placeholder': 'Ej: 2-2345678'
            }),
            'email_escuela': forms.EmailInput(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-yellow-400 focus:border-yellow-400 font-bold',
                'placeholder': 'contacto@escuela.edu.bo'
            }),
            'direccion_escuela': forms.Textarea(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-yellow-400 focus:border-yellow-400 font-bold',
                'placeholder': 'Ej: Av. Arce #123, Zona Central...',
                'rows': 2
            }),
            'apoyo_escolar': forms.CheckboxInput(attrs={
                'class': 'w-5 h-5 text-yellow-500 border-2 border-gray-300 rounded focus:ring-yellow-400'
            }),
            'observaciones_escuela': forms.Textarea(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-yellow-400 focus:border-yellow-400 font-bold',
                'placeholder': 'Notas sobre desempeño escolar, coordinación con el centro...',
                'rows': 3
            }),
            'estado': forms.Select(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-400 focus:border-blue-400 font-bold'
            }),
        }
    
    def clean_fecha_nacimiento(self):
        """Validar que la fecha de nacimiento sea válida"""
        fecha = self.cleaned_data.get('fecha_nacimiento')
        
        if fecha:
            hoy = date.today()
            if fecha > hoy:
                raise ValidationError('❌ La fecha de nacimiento no puede ser futura')
        
        return fecha
    
    def clean_telefono_tutor(self):
        """Validar formato de teléfono del tutor principal"""
        telefono = self.cleaned_data.get('telefono_tutor')
        
        if telefono:
            telefono_limpio = telefono.replace(' ', '').replace('-', '')
            if len(telefono_limpio) < 7:
                raise ValidationError('⚠️ El teléfono debe tener al menos 7 dígitos')
        
        return telefono
    
    def clean_sucursales(self):
        """Validar que se seleccione al menos una sucursal"""
        sucursales = self.cleaned_data.get('sucursales')
        
        if not sucursales or sucursales.count() == 0:
            raise ValidationError('⚠️ Debes seleccionar al menos una sucursal')
        
        return sucursales
    
    def clean(self):
        """Validaciones adicionales que requieren múltiples campos"""
        cleaned_data = super().clean()
        
        # Si hay segundo tutor, validar que tenga al menos nombre y teléfono
        nombre_tutor_2 = cleaned_data.get('nombre_tutor_2')
        telefono_tutor_2 = cleaned_data.get('telefono_tutor_2')
        
        if nombre_tutor_2 and not telefono_tutor_2:
            self.add_error('telefono_tutor_2',
                          '⚠️ Si registras un segundo tutor, debes incluir su teléfono')

        # ✅ Si hay info educativa parcial, validar coherencia mínima
        nombre_escuela = cleaned_data.get('nombre_escuela')
        telefono_escuela = cleaned_data.get('telefono_escuela')

        if telefono_escuela and not nombre_escuela:
            self.add_error('nombre_escuela',
                          '⚠️ Si ingresas teléfono de escuela, debes indicar también el nombre de la escuela')
        
        return cleaned_data

    # ✅ REMOVIDO: El método save() ya no procesa servicios
    # Los servicios se manejan directamente en las vistas (agregar_paciente y editar_paciente)