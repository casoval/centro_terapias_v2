/**
 * Autocompletar precio de sesión en PacienteServicio
 * Versión simplificada que funciona con Django Admin
 */

(function() {
    'use strict';
    
    // Esperar a que el DOM esté listo
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
    
    function init() {
        console.log('🚀 Inicializando autocomplete de precios...');
        
        // Para formulario individual de PacienteServicio
        configurarFormularioIndividual();
        
        // Para inlines en admin de Paciente
        configurarInlines();
        
        // Observar cuando se agregan nuevos inlines dinámicamente
        observarNuevosInlines();
    }
    
    function configurarFormularioIndividual() {
        const servicioSelect = document.getElementById('id_servicio');
        const costoInput = document.getElementById('id_costo_sesion');
        
        if (servicioSelect && costoInput) {
            console.log('✅ Formulario individual encontrado');
            servicioSelect.addEventListener('change', function() {
                autocompletarPrecio(servicioSelect, costoInput);
            });
            
            // Autocompletar al cargar si ya hay servicio seleccionado
            if (servicioSelect.value && !costoInput.value) {
                autocompletarPrecio(servicioSelect, costoInput);
            }
        }
    }
    
    function configurarInlines() {
        // Buscar todos los inlines de PacienteServicio
        const inlines = document.querySelectorAll('.inline-related:not(.empty-form)');
        console.log(`📋 Encontrados ${inlines.length} inlines`);
        
        inlines.forEach(function(inline, index) {
            const servicioSelect = inline.querySelector('select[name*="servicio"]');
            const costoInput = inline.querySelector('input[name*="costo_sesion"]');
            
            if (servicioSelect && costoInput) {
                console.log(`✅ Configurando inline ${index + 1}`);
                
                // Remover listeners previos (evitar duplicados)
                const newServiceSelect = servicioSelect.cloneNode(true);
                servicioSelect.parentNode.replaceChild(newServiceSelect, servicioSelect);
                
                // Agregar nuevo listener
                newServiceSelect.addEventListener('change', function() {
                    autocompletarPrecio(newServiceSelect, costoInput);
                });
                
                // Autocompletar al cargar si ya hay servicio y no hay costo
                if (newServiceSelect.value && !costoInput.value) {
                    autocompletarPrecio(newServiceSelect, costoInput);
                }
            }
        });
    }
    
    function observarNuevosInlines() {
        // Observar cuando se agregan nuevos inlines (botón "Agregar otro")
        const inlineGroup = document.querySelector('.inline-group');
        
        if (inlineGroup) {
            const observer = new MutationObserver(function(mutations) {
                mutations.forEach(function(mutation) {
                    if (mutation.addedNodes.length) {
                        console.log('🆕 Nuevo inline agregado, configurando...');
                        configurarInlines();
                    }
                });
            });
            
            observer.observe(inlineGroup, {
                childList: true,
                subtree: true
            });
        }
    }
    
    function autocompletarPrecio(servicioSelect, costoInput) {
        const servicioId = servicioSelect.value;
        
        if (!servicioId) {
            console.log('⚠️ No hay servicio seleccionado');
            return;
        }
        
        // Si ya tiene un precio (mayor a 0), preguntar si quiere sobrescribir
        if (costoInput.value && parseFloat(costoInput.value) > 0) {
            const confirmar = confirm(
                '¿Desea sobrescribir el precio actual con el precio base del servicio?'
            );
            if (!confirmar) {
                return;
            }
        }
        
        console.log(`🔍 Buscando precio para servicio ID: ${servicioId}`);
        
        // Obtener el precio base del servicio via AJAX
        fetch(`/admin/servicios/tiposervicio/${servicioId}/change/`, {
            method: 'GET',
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(response => response.text())
        .then(html => {
            // Parsear el HTML para extraer el costo_base
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, 'text/html');
            const costoBaseInput = doc.querySelector('#id_costo_base');
            
            if (costoBaseInput && costoBaseInput.value) {
                const precioBase = costoBaseInput.value;
                costoInput.value = precioBase;
                
                // Mostrar mensaje visual
                mostrarMensaje(costoInput, `💡 Precio base: Bs. ${precioBase}`);
                console.log(`✅ Precio autocompletado: Bs. ${precioBase}`);
            } else {
                console.log('⚠️ No se pudo extraer el precio base');
                mostrarMensaje(costoInput, '⚠️ No se pudo cargar el precio base', 'error');
            }
        })
        .catch(error => {
            console.error('❌ Error al cargar precio:', error);
            mostrarMensaje(costoInput, '❌ Error al cargar precio', 'error');
        });
    }
    
    function mostrarMensaje(inputElement, mensaje, tipo = 'info') {
        // Remover mensajes previos
        const prevMensaje = inputElement.parentNode.querySelector('.precio-mensaje');
        if (prevMensaje) {
            prevMensaje.remove();
        }
        
        // Crear nuevo mensaje
        const mensajeDiv = document.createElement('div');
        mensajeDiv.className = 'precio-mensaje';
        mensajeDiv.style.cssText = `
            margin-top: 5px;
            padding: 8px 12px;
            border-radius: 4px;
            font-size: 12px;
            ${tipo === 'error' 
                ? 'background: #fee; color: #c33; border: 1px solid #fcc;' 
                : 'background: #e6f7ff; color: #0066cc; border: 1px solid #91d5ff;'}
        `;
        mensajeDiv.textContent = mensaje;
        
        // Insertar después del input
        inputElement.parentNode.insertBefore(mensajeDiv, inputElement.nextSibling);
        
        // Remover después de 5 segundos
        setTimeout(function() {
            mensajeDiv.style.opacity = '0';
            mensajeDiv.style.transition = 'opacity 0.5s';
            setTimeout(function() {
                mensajeDiv.remove();
            }, 500);
        }, 5000);
    }
})();