"""Tareas programadas de asistencia (se ejecutan con cron, ver management/commands)."""
import csv
import io

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from .services import construir_panel, generar_ausentes


def generar_ausentes_diarios(fecha=None, incluir_sin_enrolar=False):
    """Compatibilidad: genera ausencias de bloques ya terminados. Devuelve un texto."""
    creadas = generar_ausentes(fecha=fecha, incluir_sin_enrolar=incluir_sin_enrolar)
    return f"Ausentes generados: {creadas}"


def enviar_reporte_diario(fecha=None):
    """Envía a RRHH el CSV del día (una fila por profesional, con todos sus bloques)."""
    fecha = fecha or timezone.localdate()
    filas, resumen = construir_panel(fecha)

    buffer = io.StringIO()
    w = csv.writer(buffer)
    w.writerow(['Profesional', 'Especialidad', 'Horario del día', 'Marcados (entrada → salida)',
                'Estado', 'Minutos tardanza', 'Ausencias (bloques)', 'Observaciones'])

    etiquetas = {'PUNTUAL': 'Puntual', 'TARDANZA': 'Tardanza', 'ausente': 'Ausente',
                 'libre': 'Día libre', 'sin_horario': 'Sin horario',
                 'pendiente': 'Pendiente', 'sin_enrolar': 'Sin enrolar'}
    for f in filas:
        marcados = ' | '.join(
            f"{timezone.localtime(e.fecha_hora):%H:%M} → "
            f"{timezone.localtime(s.fecha_hora):%H:%M}" if s else
            f"{timezone.localtime(e.fecha_hora):%H:%M} → —"
            for e, s in f['pares']
        ) or '—'
        obs = ' / '.join(e.observacion for e in f['entradas'] if e.observacion) or '—'
        w.writerow([
            f['user'].get_full_name() or f['user'].username,
            f['profesional'].especialidad if f['profesional'] else '—',
            f['horario'].descripcion(),
            marcados,
            etiquetas.get(f['estado_dia'], f['estado_dia']),
            f['minutos_tardanza'],
            ', '.join(a.bloque for a in f['ausencias']) or '—',
            obs,
        ])

    asunto = (f"Asistencia {fecha:%d/%m/%Y} — Presentes: {resumen['presentes']} | "
              f"Tardanzas: {resumen['tardanzas']} | Ausentes: {resumen['ausentes']}")
    email = EmailMessage(
        subject=asunto,
        body=(f"Resumen de asistencia del {fecha:%d/%m/%Y}:\n\n"
              f"  Presentes:  {resumen['presentes']}\n"
              f"  Tardanzas:  {resumen['tardanzas']}\n"
              f"  Ausentes:   {resumen['ausentes']}\n"
              f"  Sin enrolar: {resumen['sin_enrolar']}\n\n"
              "Adjunto el detalle completo en CSV."),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[getattr(settings, 'EMAIL_RRHH', settings.DEFAULT_FROM_EMAIL)],
    )
    email.attach(f"asistencia_{fecha:%Y%m%d}.csv", buffer.getvalue(), 'text/csv')
    email.send(fail_silently=True)
    return "Reporte enviado"
