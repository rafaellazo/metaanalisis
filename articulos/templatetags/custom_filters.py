from django import template
from decimal import Decimal, InvalidOperation

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


@register.filter
def usd(value):
    try:
        return f'${Decimal(value):,.4f}'
    except (InvalidOperation, TypeError, ValueError):
        return '$0.0000'