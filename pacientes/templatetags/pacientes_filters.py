"""
Template filters personalizados para la app de pacientes
"""
from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """
    Permite acceder a items de un diccionario usando una variable como key
    Uso en template: {{ mi_dict|get_item:mi_variable }}
    """
    if dictionary is None:
        return None
    return dictionary.get(key)