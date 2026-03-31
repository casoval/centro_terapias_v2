import subprocess
import platform
import requests
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required


@staff_member_required
def logs_whatsapp(request):
    logs = []
    try:
        if platform.system() == 'Windows':
            logs = [{'texto': 'ℹ️ Los logs solo están disponibles en el servidor de producción.', 'tipo': 'info'}]
        resultado = subprocess.run(
            ['tail', '-n', '300', '/var/log/whatsapp-bot/out.log'],
            capture_output=True, text=True
        )
        for linea in reversed(resultado.stdout.strip().split('\n')):
            if linea.strip() and any(x in linea for x in ['✅', '❌', '🚀', '📱']):
                logs.append({
                    'texto': linea.strip(),
                    'tipo': 'success' if '✅' in linea else 'error' if '❌' in linea else 'info'
                })
    except Exception as e:
        logs = [{'texto': f'Error al leer logs: {str(e)}', 'tipo': 'error'}]

    return render(request, 'recordatorios/logs_whatsapp.html', {'logs': logs})


@login_required
def whatsapp_status(request):
    try:
        res = requests.get('http://localhost:3000/status', timeout=5)
        return JsonResponse(res.json())
    except Exception:
        return JsonResponse({'status': 'desconectado'})


@login_required
def whatsapp_qr(request):
    try:
        res = requests.get('http://localhost:3000/qr', timeout=5)
        return JsonResponse(res.json())
    except Exception:
        return JsonResponse({'qr': None, 'status': 'desconectado'})


@login_required
def whatsapp_reconectar(request):
    if request.method == 'POST':
        subprocess.Popen(['pm2', 'restart', 'whatsapp-bot'])
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False})

@login_required
def whatsapp_historial(request):
    import json
    historial_japon = []
    historial_camacho = []
    try:
        with open('/var/log/whatsapp-bot/historial-japon.json', 'r') as f:
            historial_japon = json.load(f)
    except:
        pass
    try:
        with open('/var/log/whatsapp-bot/historial-camacho.json', 'r') as f:
            historial_camacho = json.load(f)
    except:
        pass
    # Combinar y ordenar por fecha
    historial = historial_japon + historial_camacho
    historial.sort(key=lambda x: x.get('fecha', ''), reverse=True)
    return JsonResponse(historial[:200], safe=False)


@login_required  
def whatsapp_envio_masivo(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False})
    import json as json_lib
    data = json_lib.loads(request.body)
    mensaje = data.get('mensaje', '').strip()
    sucursal_filtro = data.get('sucursal', 'todas')
    if not mensaje:
        return JsonResponse({'error': 'Mensaje vacío'}, status=400)

    from agenda.models import Sesion
    from django.utils import timezone
    from datetime import timedelta

    hoy = timezone.localdate()
    lunes = hoy + timedelta(days=(7 - hoy.weekday()))
    domingo = lunes + timedelta(days=6)

    sesiones = Sesion.objects.filter(
        fecha__range=[lunes, domingo],
        estado='programada',
    ).select_related('paciente', 'sucursal')

    # Recopilar tutores únicos
    tutores = {}
    for sesion in sesiones:
        paciente = sesion.paciente
        telefono = paciente.telefono_tutor
        sucursal_nombre = sesion.sucursal.nombre
        sucursal_id = sesion.sucursal.id
        if not telefono:
            continue
        if sucursal_filtro == 'japon' and sucursal_id != 3:
            continue
        if sucursal_filtro == 'camacho' and sucursal_id != 4:
            continue
        if telefono not in tutores:
            tutores[telefono] = {
                'telefono': telefono,
                'tutor_nombre': paciente.nombre_tutor,
                'paciente_nombre': paciente.nombre_completo,
                'sucursal_id': sucursal_id,
                'sucursal': sucursal_nombre,
            }

    # Enviar a cada bot según sucursal
    import requests as req_lib
    enviados = 0
    errores = 0
    for tutor in tutores.values():
        puerto = 3000 if tutor['sucursal_id'] == 3 else 3001
        try:
            req_lib.post(
                f'http://localhost:{puerto}/send',
                json={
                    'telefono': tutor['telefono'],
                    'mensaje': mensaje,
                    'paciente': tutor['paciente_nombre'],
                    'sucursal': tutor['sucursal'],
                    'delay_type': 'corto'
                },
                timeout=5
            )
            enviados += 1
        except:
            errores += 1

    return JsonResponse({'ok': True, 'enviados': enviados, 'errores': errores})