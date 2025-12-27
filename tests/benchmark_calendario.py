
import os
import django
import time
from datetime import date, timedelta
from decimal import Decimal
import sys

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db.models import Sum, Q, Count, Max, Case, When, F, Value, BooleanField
from agenda.models import Sesion, Proyecto
from pacientes.models import Paciente
from servicios.models import TipoServicio, Sucursal
from profesionales.models import Profesional

def benchmark_calendario():
    print("--- Starting Benchmark for Calendario Logic ---")
    
    # Mock request parameters
    fecha_base = date.today()
    dias_desde_lunes = fecha_base.weekday()
    fecha_inicio = fecha_base - timedelta(days=dias_desde_lunes)
    fecha_fin = fecha_inicio + timedelta(days=6)
    
    print(f"Querying range: {fecha_inicio} to {fecha_fin}")
    
    start_time = time.time()
    
    # 1. Base Query
    sesiones = Sesion.objects.select_related(
        'paciente', 'profesional', 'servicio', 'sucursal', 'proyecto'
    ).filter(
        fecha__gte=fecha_inicio,
        fecha__lte=fecha_fin
    ).order_by('fecha', 'hora_inicio')
    
    # Force evaluation
    count = sesiones.count()
    print(f"Found {count} sessions in range")
    
    # 2. Simulate User Filters (None for now to test worst case)
    sucursales_usuario = Sucursal.objects.all() # Simulate superuser
    
    # 3. Latest Session Logic (The Bottleneck)
    print("Executing Latest Session Logic (Old One)...")
    combinaciones_paciente_servicio = set()
    # We must iterate to simulate the view's behavior
    all_sesiones = list(sesiones) 
    
    for sesion in all_sesiones:
        combinaciones_paciente_servicio.add((sesion.paciente_id, sesion.servicio_id))
    
    ultimas_sesiones_ids = set()
    queries_count = 0
    
    for paciente_id_combo, servicio_id_combo in combinaciones_paciente_servicio:
        ultima_sesion = Sesion.objects.filter(
            paciente_id=paciente_id_combo,
            servicio_id=servicio_id_combo,
            estado__in=['programada', 'realizada', 'realizada_retraso']
        ).order_by('-fecha', '-hora_inicio').first()
        queries_count += 1
        
        if ultima_sesion:
            ultimas_sesiones_ids.add(ultima_sesion.id)
            
    print(f"Performed {queries_count} extra queries for latest sessions")
            
    # 4. Statistics Calculation
    print("Executing Statistics Calculation...")
    
    # The view recalculates totals using python loops over annotated querysets
    # We simulate the heavy part: payments calculation
    sesiones_con_pagos = sesiones.annotate(
        total_pagado_sesion=Sum('pagos__monto', filter=Q(pagos__anulado=False))
    )
    
    sesiones_list = list(sesiones_con_pagos)
    
    total_pendiente = sum(
        max(s.monto_cobrado - (s.total_pagado_sesion or Decimal('0.00')), Decimal('0.00'))
        for s in sesiones_list
    )
    
    count_pagados = sum(
        1 for s in sesiones_list 
        if s.monto_cobrado > 0 and (s.total_pagado_sesion or Decimal('0.00')) >= s.monto_cobrado
    )
    
    end_time = time.time()
    duration = end_time - start_time
    
    print(f"--- Benchmark Completed in {duration:.4f} seconds ---")
    return duration

if __name__ == "__main__":
    benchmark_calendario()
