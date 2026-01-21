from django import forms
from django.core.exceptions import ValidationError
from .models import Paciente, PacienteServicio
from servicios.models import TipoServicio, Sucursal
from datetime import date


class PacienteForm(forms.ModelForm):
    """
    Formulario personalizado para crear/editar pacientes
    ✅ CON FILTRADO DE SUCURSALES SEGÚN ROL DEL USUARIO
    """
    
    def __init__(self, *args, **kwargs):
        # ✅ RECIBIR USUARIO PARA FILTRAR SUCURSALES
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # ✅ FILTRADO DE SUCURSALES SEGÚN ROL DEL USUARIO
        if user:
            if user.is_superuser:
                # Superadmin: Todas las sucursales activas
                self.fields['sucursales'].queryset = Sucursal.objects.filter(activa=True).order_by('nombre')
            elif hasattr(user, 'perfil'):
                if user.perfil.es_gerente():
                    # Gerente: Todas las sucursales activas
                    self.fields['sucursales'].queryset = Sucursal.objects.filter(activa=True).order_by('nombre')
                elif user.perfil.es_recepcionista():
                    # ✅ RECEPCIONISTA: Solo sus sucursales asignadas
                    mis_sucursales = user.perfil.sucursales.filter(activa=True)
                    self.fields['sucursales'].queryset = mis_sucursales.order_by('nombre')
                    
                    # ✅ MENSAJE INFORMATIVO si no tiene sucursales
                    if not mis_sucursales.exists():
                        self.fields['sucursales'].help_text = '⚠️ No tienes sucursales asignadas. Contacta al administrador.'
                else:
                    # Otros roles: Sin sucursales
                    self.fields['sucursales'].queryset = Sucursal.objects.none()
            else:
                self.fields['sucursales'].queryset = Sucursal.objects.none()
        else:
            # Sin usuario: Todas las sucursales (fallback para compatibilidad)
            self.fields['sucursales'].queryset = Sucursal.objects.filter(activa=True).order_by('nombre')
        
        # ✅ FILTRAR: Solo usuarios con rol "paciente" que NO estén vinculados
        from core.models import PerfilUsuario
        from django.contrib.auth.models import User
        
        # Paso 1: Obtener usuarios base con rol paciente (excluir superusuarios)
        usuarios_base = User.objects.filter(
            perfil__rol='paciente'
        ).exclude(is_superuser=True)
        
        # Paso 2: Filtrar según si estamos creando o editando
        if self.instance and self.instance.pk and self.instance.user:
            # EDITANDO un paciente que tiene user vinculado
            # Mostrar SOLO: usuarios sin paciente + el usuario actual de este paciente
            usuarios_disponibles = usuarios_base.filter(
                paciente__isnull=True  # Usuarios sin paciente vinculado
            ) | User.objects.filter(
                id=self.instance.user.id  # MÁS el usuario actual
            )
        else:
            # CREANDO nuevo paciente O editando uno sin user
            # Mostrar SOLO usuarios sin paciente vinculado
            usuarios_disponibles = usuarios_base.filter(
                paciente__isnull=True
            )
        
        self.fields['user'].queryset = usuarios_disponibles.distinct()
        
        # ✅ Personalizar cómo se muestra cada usuario en el dropdown
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
            'estado': forms.Select(attrs={
                'class': 'w-full px-4 py-2.5 border-2 border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-400 focus:border-blue-400 font-bold'
            }),
        }
    
    def clean_fecha_nacimiento(self):
        """Validar que la fecha de nacimiento sea válida"""
        fecha = self.cleaned_data.get('fecha_nacimiento')
        
        if fecha:
            hoy = date.today()
            
            # No puede ser fecha futura
            if fecha > hoy:
                raise ValidationError('❌ La fecha de nacimiento no puede ser futura')
        
        return fecha
    
    def clean_telefono_tutor(self):
        """Validar formato de teléfono del tutor principal"""
        telefono = self.cleaned_data.get('telefono_tutor')
        
        if telefono:
            # Remover espacios y guiones
            telefono_limpio = telefono.replace(' ', '').replace('-', '')
            
            # Debe tener al menos 7 dígitos
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
        
        return cleaned_data
    
    def save(self, commit=True):
        """Guardar paciente y servicios seleccionados con precios/observaciones"""
        paciente = super().save(commit=commit)
        
        if commit:
            # Procesar servicios desde POST data
            servicios = TipoServicio.objects.filter(activo=True)
            
            for servicio in servicios:
                # Verificar si el servicio fue seleccionado (checkbox marcado)
                servicio_key = f'servicio_{servicio.id}'
                if servicio_key in self.data:
                    # Obtener precio personalizado
                    precio_key = f'precio_{servicio.id}'
                    precio_custom = self.data.get(precio_key, '').strip()
                    
                    # Si está vacío o es 0, usar precio base
                    if not precio_custom or float(precio_custom or 0) == 0:
                        precio_custom = servicio.costo_base
                    else:
                        precio_custom = float(precio_custom)
                    
                    # Obtener observaciones
                    obs_key = f'obs_{servicio.id}'
                    observaciones = self.data.get(obs_key, '').strip()
                    
                    # Crear relación PacienteServicio
                    PacienteServicio.objects.get_or_create(
                        paciente=paciente,
                        servicio=servicio,
                        defaults={
                            'costo_sesion': precio_custom,
                            'observaciones': observaciones,
                            'activo': True
                        }
                    )
        
        return paciente