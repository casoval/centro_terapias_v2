from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction

from servicios.models import Sucursal, TipoServicio


class TitularInventario(models.Model):
    """
    "Dueño" de un inventario. Puede ser:
      - 'centro'    → bolsa general del centro (destino por defecto de las
                       transferencias que un profesional deja "para que el
                       admin verifique").
      - 'sucursal'  → inventario de una sucursal.
      - 'servicio'  → inventario de un tipo de servicio/terapia.
      - 'usuario'   → inventario personal de CUALQUIER usuario staff
                       (profesional, recepcionista o gerente).

    Se crean bajo demanda (get_or_create) la primera vez que alguien
    necesita ver/sumar stock a un titular — ver InventarioService.
    """

    TIPO_CHOICES = [
        ('centro', 'Centro (general)'),
        ('sucursal', 'Sucursal'),
        ('servicio', 'Servicio'),
        ('usuario', 'Usuario'),
    ]

    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, null=True, blank=True, related_name='titulares_inventario')
    servicio = models.ForeignKey(TipoServicio, on_delete=models.CASCADE, null=True, blank=True, related_name='titulares_inventario')
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='titulares_inventario')

    class Meta:
        verbose_name = 'Titular de Inventario'
        verbose_name_plural = 'Titulares de Inventario'
        constraints = [
            models.UniqueConstraint(fields=['tipo'], condition=models.Q(tipo='centro'), name='unico_titular_centro'),
            models.UniqueConstraint(fields=['tipo', 'sucursal'], condition=models.Q(tipo='sucursal'), name='unico_titular_sucursal'),
            models.UniqueConstraint(fields=['tipo', 'servicio'], condition=models.Q(tipo='servicio'), name='unico_titular_servicio'),
            models.UniqueConstraint(fields=['tipo', 'usuario'], condition=models.Q(tipo='usuario'), name='unico_titular_usuario'),
        ]

    def clean(self):
        campos = {'sucursal': self.sucursal, 'servicio': self.servicio, 'usuario': self.usuario}
        requerido = {'centro': None, 'sucursal': 'sucursal', 'servicio': 'servicio', 'usuario': 'usuario'}[self.tipo]
        for nombre, valor in campos.items():
            if nombre == requerido:
                if not valor:
                    raise ValidationError(f'Un titular de tipo "{self.tipo}" requiere el campo "{nombre}".')
            elif valor:
                raise ValidationError(f'Un titular de tipo "{self.tipo}" no debe tener el campo "{nombre}".')

    def __str__(self):
        if self.tipo == 'centro':
            return '🏢 Centro (general)'
        if self.tipo == 'sucursal':
            return f'🏬 {self.sucursal.nombre}'
        if self.tipo == 'servicio':
            return f'🩺 {self.servicio.nombre}'
        return f'👤 {self.usuario.get_full_name() or self.usuario.username}'

    # ---- helpers de creación bajo demanda ----

    @classmethod
    def del_centro(cls):
        obj, _ = cls.objects.get_or_create(tipo='centro')
        return obj

    @classmethod
    def de_sucursal(cls, sucursal):
        obj, _ = cls.objects.get_or_create(tipo='sucursal', sucursal=sucursal)
        return obj

    @classmethod
    def de_servicio(cls, servicio):
        obj, _ = cls.objects.get_or_create(tipo='servicio', servicio=servicio)
        return obj

    @classmethod
    def de_usuario(cls, usuario):
        obj, _ = cls.objects.get_or_create(tipo='usuario', usuario=usuario)
        return obj


class CategoriaItemInventario(models.Model):
    """Categoría simple para ordenar el catálogo (Ej: 'Material terapéutico', 'Oficina', 'Limpieza')."""
    nombre = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = 'Categoría de Ítem'
        verbose_name_plural = 'Categorías de Ítems'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class ItemInventario(models.Model):
    """
    Catálogo maestro de tipos de ítems (no es stock en sí). Solo
    admin/gerente crean, editan o desactivan ítems del catálogo, para
    evitar duplicados y mantener el inventario ordenado.
    """
    UNIDAD_CHOICES = [
        ('unidad', 'Unidad'),
        ('caja', 'Caja'),
        ('paquete', 'Paquete'),
        ('par', 'Par'),
        ('kit', 'Kit'),
        ('litro', 'Litro'),
        ('kg', 'Kilogramo'),
        ('resma', 'Resma'),
    ]

    nombre = models.CharField(max_length=150, unique=True)
    descripcion = models.CharField(max_length=255, blank=True)
    categoria = models.ForeignKey(CategoriaItemInventario, on_delete=models.SET_NULL, null=True, blank=True, related_name='items')
    unidad = models.CharField(max_length=20, choices=UNIDAD_CHOICES, default='unidad')
    activo = models.BooleanField(default=True)
    creado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='items_inventario_creados')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Ítem de Inventario'
        verbose_name_plural = 'Ítems de Inventario'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class StockInventario(models.Model):
    """"Foto" actual de cuánto tiene cada titular de cada ítem."""
    titular = models.ForeignKey(TitularInventario, on_delete=models.CASCADE, related_name='stock')
    item = models.ForeignKey(ItemInventario, on_delete=models.PROTECT, related_name='stock')
    cantidad = models.PositiveIntegerField(default=0)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Stock'
        verbose_name_plural = 'Stock'
        unique_together = ('titular', 'item')
        ordering = ['item__nombre']

    def __str__(self):
        return f'{self.item.nombre} × {self.cantidad} — {self.titular}'


class MovimientoInventario(models.Model):
    """
    Bitácora de auditoría: TODO cambio de stock queda registrado acá.
    Nunca se edita ni se borra un movimiento ya creado.
    """
    TIPO_CHOICES = [
        ('entrada', 'Entrada / Agregado'),
        ('ajuste', 'Ajuste (admin)'),
        ('transferencia_salida', 'Transferencia — salida'),
        ('transferencia_entrada', 'Transferencia — entrada'),
        ('baja', 'Baja / Eliminación (admin)'),
    ]

    titular = models.ForeignKey(TitularInventario, on_delete=models.CASCADE, related_name='movimientos')
    item = models.ForeignKey(ItemInventario, on_delete=models.PROTECT, related_name='movimientos')
    tipo = models.CharField(max_length=25, choices=TIPO_CHOICES)
    cantidad = models.IntegerField(help_text='Positivo = suma al stock, negativo = resta.')
    motivo = models.CharField(max_length=255, blank=True)
    realizado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='movimientos_inventario')
    fecha = models.DateTimeField(auto_now_add=True)
    transferencia = models.ForeignKey(
        'TransferenciaInventario', on_delete=models.SET_NULL, null=True, blank=True, related_name='movimientos',
    )

    class Meta:
        verbose_name = 'Movimiento de Inventario'
        verbose_name_plural = 'Movimientos de Inventario'
        ordering = ['-fecha']
        indexes = [models.Index(fields=['-fecha']), models.Index(fields=['titular', 'item'])]

    def __str__(self):
        signo = '+' if self.cantidad >= 0 else ''
        return f'{self.get_tipo_display()} {signo}{self.cantidad} {self.item.nombre} — {self.titular}'


class TransferenciaInventario(models.Model):
    """
    Solicitud de traspaso de stock entre titulares. Un usuario común NUNCA
    puede restar directamente de su inventario: solo puede *solicitar* una
    transferencia. El stock real se mueve recién cuando el admin la aprueba
    (de forma atómica: resta en origen + suma en destino + 2 movimientos).
    """
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente de verificación'),
        ('aprobada', 'Aprobada'),
        ('rechazada', 'Rechazada'),
    ]

    MOTIVO_CHOICES = [
        ('deja_de_trabajar', 'Profesional/usuario deja de trabajar'),
        ('dañado', 'Ítem dañado'),
        ('perdido', 'Ítem perdido'),
        ('reasignacion', 'Reasignación de trabajo'),
        ('otro', 'Otro'),
    ]

    origen = models.ForeignKey(TitularInventario, on_delete=models.CASCADE, related_name='transferencias_salida')
    # destino puede quedar vacío al solicitar → se interpreta como "dejar en el Centro"
    destino = models.ForeignKey(TitularInventario, on_delete=models.CASCADE, null=True, blank=True, related_name='transferencias_entrada')
    item = models.ForeignKey(ItemInventario, on_delete=models.PROTECT, related_name='transferencias')
    cantidad = models.PositiveIntegerField()
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='pendiente')
    motivo = models.CharField(max_length=20, choices=MOTIVO_CHOICES, default='otro')
    notas_solicitante = models.CharField(max_length=255, blank=True)
    notas_admin = models.CharField(max_length=255, blank=True)

    solicitado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='transferencias_solicitadas')
    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    resuelto_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='transferencias_resueltas')
    fecha_resolucion = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Transferencia de Inventario'
        verbose_name_plural = 'Transferencias de Inventario'
        ordering = ['-fecha_solicitud']

    def __str__(self):
        return f'{self.item.nombre} × {self.cantidad}: {self.origen} → {self.destino or "Centro (pendiente)"}'

    @property
    def destino_mostrado(self):
        return self.destino or TitularInventario.del_centro()

    @transaction.atomic
    def aprobar(self, admin_user, notas=''):
        if self.estado != 'pendiente':
            raise ValidationError('Esta transferencia ya fue resuelta.')

        destino_real = self.destino or TitularInventario.del_centro()

        stock_origen, _ = StockInventario.objects.select_for_update().get_or_create(titular=self.origen, item=self.item)
        if stock_origen.cantidad < self.cantidad:
            raise ValidationError(
                f'El origen ya no tiene suficiente stock ({stock_origen.cantidad} disponibles, se solicitaron {self.cantidad}).'
            )
        stock_destino, _ = StockInventario.objects.select_for_update().get_or_create(titular=destino_real, item=self.item)

        stock_origen.cantidad -= self.cantidad
        stock_origen.save(update_fields=['cantidad'])
        stock_destino.cantidad += self.cantidad
        stock_destino.save(update_fields=['cantidad'])

        MovimientoInventario.objects.create(
            titular=self.origen, item=self.item, tipo='transferencia_salida',
            cantidad=-self.cantidad, motivo=f'Transferencia #{self.pk}: {self.get_motivo_display()}',
            realizado_por=admin_user, transferencia=self,
        )
        MovimientoInventario.objects.create(
            titular=destino_real, item=self.item, tipo='transferencia_entrada',
            cantidad=self.cantidad, motivo=f'Transferencia #{self.pk}: {self.get_motivo_display()}',
            realizado_por=admin_user, transferencia=self,
        )

        self.destino = destino_real
        self.estado = 'aprobada'
        self.resuelto_por = admin_user
        self.notas_admin = notas
        from django.utils import timezone
        self.fecha_resolucion = timezone.now()
        self.save()

    def rechazar(self, admin_user, notas=''):
        if self.estado != 'pendiente':
            raise ValidationError('Esta transferencia ya fue resuelta.')
        self.estado = 'rechazada'
        self.resuelto_por = admin_user
        self.notas_admin = notas
        from django.utils import timezone
        self.fecha_resolucion = timezone.now()
        self.save()
