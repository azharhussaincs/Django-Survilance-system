"""
Custom template tags and filters for the NVR surveillance system.
"""
from django import template
from django.utils.html import format_html

register = template.Library()


@register.filter
def brand_color(brand: str) -> str:
    """Return a CSS color for the given NVR brand."""
    colors = {
        'hikvision': '#00d4ff',
        'cpplus':    '#f0b429',
        'dahua':     '#a78bfa',
        'generic':   '#3fb950',
        'unknown':   '#7d8590',
    }
    return colors.get(brand, '#7d8590')


@register.filter
def brand_class(brand: str) -> str:
    """Return a CSS class for the given NVR brand badge."""
    classes = {
        'hikvision': 'badge-hikvision',
        'cpplus':    'badge-cpplus',
        'dahua':     'badge-dahua',
        'generic':   'badge-generic',
        'unknown':   'badge-unknown',
    }
    return classes.get(brand, 'badge-unknown')


@register.filter
def camera_count(nvr) -> int:
    """Return the active camera count for an NVR."""
    try:
        return nvr.cameras.filter(is_active=True).count()
    except Exception:
        return 0


@register.simple_tag
def status_dot(is_connected: bool) -> str:
    """Render a coloured status dot."""
    color = '#3fb950' if is_connected else '#7d8590'
    return format_html(
        '<span style="display:inline-block;width:8px;height:8px;'
        'border-radius:50%;background:{};margin-right:6px"></span>',
        color
    )
