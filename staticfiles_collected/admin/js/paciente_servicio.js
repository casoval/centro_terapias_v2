/**
 * Script para autocompletar costo y mostrar precio base en inline de servicios
 */

(function() {
    'use strict';
    
    // Esperar a que Django Admin esté listo
    if (typeof django === 'undefined' || !django.jQuery) {
        console.error('Django jQuery no disponible');
        return;
    }
    
    const $ = django.jQuery;
    
    /**
     * Actualiza el precio base y autocompleta el costo
     */
    function actualizarPrecioBase(selectServicio) {
        const $select = $(selectServicio);
        const $row = $select.closest('tr');
        
        // Encontrar el input de costo_sesion
        const $costoInput = $row.find('input[id$="-costo_sesion"]');
        
        // Encontrar la celda del precio base (readonly field)
        const $precioBaseCell = $row.find('td.field-precio_base_display');
        
        if (!$select.val()) {
            // Si no hay servicio seleccionado
            if ($precioBaseCell.length) {
                $precioBaseCell.html('<span style="color: #6b7280;">-</span>');
            }
            return;
        }
        
        // Obtener el precio base del option seleccionado
        const $selectedOption = $select.find('option:selected');
        const servicioText = $selectedOption.text();
        
        // Extraer el precio del texto (formato: "Servicio - Bs. 150.00")
        const precioMatch = servicioText.match(/Bs\.\s*([\d,.]+)/);
        
        if (precioMatch) {
            const precioBase = precioMatch[1].replace(',', '');
            
            // Actualizar el display del precio base
            if ($precioBaseCell.length) {
                $precioBaseCell.html(
                    `<span style="color: #059669; font-weight: bold;">Bs. ${precioBase}</span>`
                );
            }
            
            // Autocompletar costo_sesion si está vacío
            const costoActual = $costoInput.val();
            if (!costoActual || costoActual === '0' || costoActual === '0.00' || costoActual === '') {
                $costoInput.val(precioBase);
                
                // Resaltar visualmente
                $costoInput.css('background-color', '#f0fdf4');
                setTimeout(function() {
                    $costoInput.css('background-color', '');
                }, 1500);
            }
        }
    }
    
    /**
     * Inicializar eventos para un select de servicio
     */
    function initSelectServicio($select) {
        $select.on('change', function() {
            actualizarPrecioBase(this);
        });
        
        // Actualizar al cargar si ya tiene valor
        if ($select.val()) {
            actualizarPrecioBase($select[0]);
        }
    }
    
    /**
     * Inicializar todos los selects existentes
     */
    function initAllSelects() {
        $('select[id$="-servicio"]').each(function() {
            initSelectServicio($(this));
        });
    }
    
    // Inicializar cuando el DOM esté listo
    $(document).ready(function() {
        initAllSelects();
        
        // Detectar cuando se añade una nueva fila al inline
        $('.add-row a, .add-row button').on('click', function() {
            setTimeout(function() {
                initAllSelects();
            }, 100);
        });
    });
    
})();