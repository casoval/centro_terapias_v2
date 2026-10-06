from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import PerfilUsuario


@receiver(post_save, sender=PerfilUsuario)
def crear_enrolamiento_facial(sender, instance, **kwargs):
    """
    Crea el registro de enrolamiento cuando un usuario pasa a ser profesional.

    Se engancha a PerfilUsuario (no a User): al crearse el User todavía no existe su
    perfil/rol, por eso la señal anterior sobre User nunca llegaba a crearlo.
    """
    if instance.rol != 'profesional' or instance.user.is_superuser:
        return
    from .models import EnrolamientoFacial
    EnrolamientoFacial.objects.get_or_create(user=instance.user)
