
import os
import django
import sys
from datetime import date, timedelta
from decimal import Decimal

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db.models import Sum, Q, Count, F, OuterRef, Subquery, Case, When, DecimalField
from django.db.models.functions import Coalesce
from agenda.models import Sesion

def verify_new_logic():
    print("--- Verifying New Optimization Logic ---")
    
    # 1. Test Subquery logic
    print("Testing Subquery annotation...")
    try:
        latest_sesion_sq = Sesion.objects.filter(
            paciente=OuterRef('paciente'),
            servicio=OuterRef('servicio'),
            estado__in=['programada', 'realizada', 'realizada_retraso']
        ).order_by('-fecha', '-hora_inicio').values('id')[:1]
        
        qs = Sesion.objects.all().annotate(
            latest_sesion_id=Subquery(latest_sesion_sq)
        )
        # Execute query
        print(f"Query executed successfully. Count: {qs.count()}")
        
        if qs.exists():
            item = qs.first()
            print(f"Sample item latest_id: {item.latest_sesion_id}")
            
    except Exception as e:
        print(f"❌ Error in Subquery logic: {e}")
        return

    # 2. Test Aggregation Logic
    print("Testing Aggregation logic...")
    try:
        sesiones_con_pagos = Sesion.objects.all().annotate(
            total_pagado_sesion=Coalesce(Sum('pagos__monto', filter=Q(pagos__anulado=False)), Decimal('0.00'))
        )
        
        stats = sesiones_con_pagos.aggregate(
            total_pagado=Sum('total_pagado_sesion'),
            total_pendiente=Sum(
                 Case(
                     When(monto_cobrado__gt=F('total_pagado_sesion'), then=F('monto_cobrado') - F('total_pagado_sesion')),
                     default=Decimal('0.00'),
                     output_field=DecimalField()
                 )
            ),
            count_pagados=Count(
                Case(
                    When(monto_cobrado__gt=0, total_pagado_sesion__gte=F('monto_cobrado'), then=1),
                    output_field=DecimalField()
                )
            ),
            count_pendientes=Count(
                Case(
                    When(monto_cobrado__gt=0, total_pagado_sesion__lt=F('monto_cobrado'), then=1),
                    output_field=DecimalField()
                )
            )
        )
        print(f"Aggregation executed successfully. Stats: {stats}")
        
    except Exception as e:
        print(f"❌ Error in Aggregation logic: {e}")
        return

    print("✅ All new logic verified successfully!")

if __name__ == "__main__":
    verify_new_logic()
