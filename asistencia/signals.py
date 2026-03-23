from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User


@receiver(post_save, sender=User)
def crear_enrolamiento_facial(sender, instance, created, **kwargs):
    """Crea automáticamente el registro de enrolamiento cuando se crea un usuario profesional."""
    if not created:
        return
    if instance.is_superuser:
        return
    try:
        if hasattr(instance, 'perfil') and instance.perfil.rol == 'profesional':
            from .models import EnrolamientoFacial
            EnrolamientoFacial.objects.get_or_create(user=instance)
    except Exception:
        pass


# ── Tareas programadas (sin Celery por ahora) ────────────────────────────────
# Estas funciones se pueden llamar manualmente desde una vista o desde
# un cron job / manage.py command cuando se necesite.

def generar_ausentes_diarios():
    """
    Genera registros AUSENTE para profesionales sin entrada en el día indicado.
    Llamar al cierre de jornada, ej: desde un management command o cron.
    """
    from .models import RegistroAsistencia, ConfigAsistencia
    from django.utils import timezone

    hoy = timezone.now().date()
    profesionales = User.objects.filter(
        perfil__rol='profesional', is_active=True
    )

    ausentes = []
    for user in profesionales:
        tiene_entrada = user.registros_asistencia.filter(
            fecha_hora__date=hoy,
            tipo='ENTRADA',
            estado__in=['PUNTUAL', 'TARDANZA'],
        ).exists()

        if not tiene_entrada:
            zona = None
            config = ConfigAsistencia.objects.filter(user=user).first()
            if config:
                zona = config.zona

            _, creado = RegistroAsistencia.objects.get_or_create(
                user=user,
                tipo='ENTRADA',
                fecha_hora__date=hoy,
                defaults={
                    'tipo': 'ENTRADA',
                    'estado': 'AUSENTE',
                    'fecha_hora': timezone.now().replace(hour=20, minute=0, second=0),
                    'zona': zona,
                }
            )
            if creado:
                ausentes.append(user.get_full_name())

    return f"Ausentes generados: {len(ausentes)}"


def enviar_reporte_diario():
    """
    Genera y envía el reporte CSV diario a RRHH por email.
    Llamar al cierre de jornada.
    """
    import csv
    import io
    from django.core.mail import EmailMessage
    from django.conf import settings
    from django.utils import timezone
    from .models import RegistroAsistencia

    hoy = timezone.now().date()
    profesionales = User.objects.filter(
        perfil__rol='profesional', is_active=True
    ).select_related('perfil__profesional')

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        'Profesional', 'Especialidad', 'Entrada', 'Salida',
        'Estado', 'Minutos tardanza', 'Observación'
    ])

    resumen = {'puntuales': 0, 'tardanzas': 0, 'ausentes': 0}

    for user in profesionales:
        registros_hoy = user.registros_asistencia.filter(fecha_hora__date=hoy)
        entrada = registros_hoy.filter(tipo='ENTRADA', estado__in=['PUNTUAL', 'TARDANZA']).first()
        salida = registros_hoy.filter(tipo='SALIDA', estado__in=['PUNTUAL', 'TARDANZA']).first()

        profesional = getattr(getattr(user, 'perfil', None), 'profesional', None)
        especialidad = profesional.especialidad if profesional else '—'

        if entrada:
            estado_dia = entrada.estado
            if entrada.estado == 'TARDANZA':
                resumen['tardanzas'] += 1
            else:
                resumen['puntuales'] += 1
        else:
            estado_dia = 'AUSENTE'
            resumen['ausentes'] += 1

        writer.writerow([
            user.get_full_name(),
            especialidad,
            entrada.fecha_hora.strftime('%H:%M') if entrada else '—',
            salida.fecha_hora.strftime('%H:%M') if salida else '—',
            estado_dia,
            entrada.minutos_tardanza if entrada else 0,
            entrada.observacion if entrada and entrada.observacion else '—',
        ])

    email_rrhh = getattr(settings, 'EMAIL_RRHH', settings.DEFAULT_FROM_EMAIL)
    asunto = (
        f"Asistencia {hoy.strftime('%d/%m/%Y')} — "
        f"Puntuales: {resumen['puntuales']} | "
        f"Tardanzas: {resumen['tardanzas']} | "
        f"Ausentes: {resumen['ausentes']}"
    )

    email = EmailMessage(
        subject=asunto,
        body=(
            f"Resumen de asistencia del {hoy.strftime('%d/%m/%Y')}:\n\n"
            f"  Puntuales:  {resumen['puntuales']}\n"
            f"  Tardanzas:  {resumen['tardanzas']}\n"
            f"  Ausentes:   {resumen['ausentes']}\n\n"
            "Adjunto el detalle completo en CSV."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email_rrhh],
    )
    email.attach(
        f"asistencia_{hoy.strftime('%Y%m%d')}.csv",
        buffer.getvalue(),
        'text/csv'
    )
    email.send(fail_silently=True)
    return "Reporte enviado"