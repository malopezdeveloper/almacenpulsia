from django import template

register = template.Library()

@register.filter
def get_item(mapping, key):
    if not isinstance(mapping, dict):
        return ""
    value = mapping.get(key, "")
    if value is True:
        return "Sí"
    if value is False:
        return "No"
    return value
