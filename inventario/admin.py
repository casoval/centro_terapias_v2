from django.contrib import admin
from .models import (
    TitularInventario, CategoriaItemInventario, ItemInventario,
    StockInventario, MovimientoInventario, TransferenciaInventario,
)


@admin.register(TitularInventario)
class TitularInventarioAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'tipo', 'sucursal', 'servicio', 'usuario')
    list_filter = ('tipo',)
    search_fields = ('sucursal__nombre', 'servicio__nombre', 'usuario__username', 'usuario__first_name', 'usuario__last_name')
    autocomplete_fields = ('sucursal', 'servicio', 'usuario')


@admin.register(CategoriaItemInventario)
class CategoriaItemInventarioAdmin(admin.ModelAdmin):
    list_display = ('nombre',)
    search_fields = ('nombre',)


@admin.register(ItemInventario)
class ItemInventarioAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'categoria', 'unidad', 'activo', 'creado_por', 'fecha_creacion')
    list_filter = ('activo', 'categoria', 'unidad')
    search_fields = ('nombre',)


@admin.register(StockInventario)
class StockInventarioAdmin(admin.ModelAdmin):
    list_display = ('titular', 'item', 'cantidad', 'fecha_actualizacion')
    list_filter = ('titular__tipo',)
    search_fields = ('item__nombre',)
    autocomplete_fields = ('titular', 'item')


@admin.register(MovimientoInventario)
class MovimientoInventarioAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'tipo', 'titular', 'item', 'cantidad', 'realizado_por')
    list_filter = ('tipo', 'fecha')
    search_fields = ('item__nombre', 'motivo')
    autocomplete_fields = ('titular', 'item', 'realizado_por', 'transferencia')
    readonly_fields = ('fecha',)


@admin.register(TransferenciaInventario)
class TransferenciaInventarioAdmin(admin.ModelAdmin):
    list_display = ('item', 'cantidad', 'origen', 'destino', 'estado', 'solicitado_por', 'fecha_solicitud')
    list_filter = ('estado', 'motivo', 'fecha_solicitud')
    search_fields = ('item__nombre', 'notas_solicitante', 'notas_admin')
    autocomplete_fields = ('origen', 'destino', 'item', 'solicitado_por', 'resuelto_por')
    readonly_fields = ('fecha_solicitud', 'fecha_resolucion')
