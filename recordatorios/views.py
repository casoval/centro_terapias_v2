import subprocess
import platform
import requests
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required


@login_required
def logs_whatsapp(request):
    logs = []
    try:
        if platform.system() == 'Windows':
            logs = [{'texto': 'ℹ️ Los logs solo están disponibles en el servidor de producción.', 'tipo': 'info'}]
        else:
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
    bot = request.GET.get('bot', 'japon')
    puerto = 3000 if bot == 'japon' else 3001
    try:
        res = requests.get(f'http://localhost:{puerto}/status', timeout=5)
        return JsonResponse(res.json())
    except:
        return JsonResponse({'status': 'desconectado'})

@login_required
def whatsapp_qr(request):
    bot = request.GET.get('bot', 'japon')
    puerto = 3000 if bot == 'japon' else 3001
    try:
        res = requests.get(f'http://localhost:{puerto}/qr', timeout=5)
        return JsonResponse(res.json())
    except:
        return JsonResponse({'qr': None, 'status': 'desconectado'})

@login_required
def whatsapp_reconectar(request):
    if request.method == 'POST':
        import json as json_lib
        data = json_lib.loads(request.body)
        bot = data.get('bot', 'japon')
        puerto = 3000 if bot == 'japon' else 3001
        subprocess.Popen(['pm2', 'restart', f'whatsapp-bot{"-camacho" if bot == "camacho" else ""}'])
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
    destinatarios = data.get('destinatarios', 'semana')
    if not mensaje:
        return JsonResponse({'error': 'Mensaje vacío'}, status=400)

    from agenda.models import Sesion
    from pacientes.models import Paciente
    from django.utils import timezone
    from datetime import timedelta

    tutores = {}

    if destinatarios == 'semana':
        hoy = timezone.localdate()
        lunes = hoy + timedelta(days=(7 - hoy.weekday()))
        domingo = lunes + timedelta(days=6)
        sesiones = Sesion.objects.filter(
            fecha__range=[lunes, domingo],
            estado='programada',
        ).select_related('paciente', 'sucursal')
        for sesion in sesiones:
            paciente = sesion.paciente
            telefono = paciente.telefono_tutor
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
                    'sucursal': sesion.sucursal.nombre,
                }

    elif destinatarios == 'todos':
        pacientes = Paciente.objects.filter(estado='activo')
        
        if sucursal_filtro == 'japon':
            pacientes = pacientes.filter(sucursales__id=3)
        elif sucursal_filtro == 'camacho':
            pacientes = pacientes.filter(sucursales__id=4)

        for paciente in pacientes:
            telefono = paciente.telefono_tutor
            if not telefono:
                continue
            # Determinar sucursal principal para elegir el bot
            sucursal_id = 3  # default Japón
            sucursal_nombre = 'Suc. Japon'
            if paciente.sucursales.filter(id=4).exists():
                sucursal_id = 4
                sucursal_nombre = 'Suc. Camacho'
            # Si filtramos por sucursal específica, respetar eso
            if sucursal_filtro == 'japon':
                sucursal_id = 3
                sucursal_nombre = 'Suc. Japon'
            elif sucursal_filtro == 'camacho':
                sucursal_id = 4
                sucursal_nombre = 'Suc. Camacho'

            if telefono not in tutores:
                tutores[telefono] = {
                    'telefono': telefono,
                    'tutor_nombre': paciente.nombre_tutor,
                    'paciente_nombre': paciente.nombre_completo,
                    'sucursal_id': sucursal_id,
                    'sucursal': sucursal_nombre,
                }

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