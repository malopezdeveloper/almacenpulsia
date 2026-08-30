from django import template
from inventory.order_models import CustomerOrder

register = template.Library()

@register.simple_tag
def stock_destination_orders():
    return CustomerOrder.objects.filter(status='open').exclude(name__iexact='stock').select_related('customer').order_by('-id')
