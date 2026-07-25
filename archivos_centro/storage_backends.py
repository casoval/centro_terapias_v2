"""
Storage para los Archivos del Centro.

Reutiliza exactamente el mismo backend de Cloudflare R2 configurado para
`documentos` (documentos.storage_backends.get_documentos_storage), ya que
es un backend genérico (no específico de pacientes): mismo bucket privado,
mismas URLs firmadas con expiración. Los archivos de este módulo se
diferencian solo por el prefijo `upload_to` en el FileField del modelo.

Si R2 no está configurado (dev local sin variables de entorno), cae
automáticamente al storage local (MEDIA_ROOT), igual que `documentos`.
"""

from documentos.storage_backends import get_documentos_storage

get_archivos_centro_storage = get_documentos_storage
