from django import template
from inventory.models import ProductionZone

register = template.Library()


@register.simple_tag
def active_reservation_zones():
    return ProductionZone.objects.filter(is_active=True).order_by('position', 'name')
