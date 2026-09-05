from django import template

register = template.Library()


@register.simple_tag
def unit_pallet_state(unit):
    try:
        membership = unit.pallet_membership
        return 'shipped' if membership.pallet.status == 'shipped' else 'pallet'
    except Exception:
        return ''
