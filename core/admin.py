"""
Django Admin configuration for NVR Surveillance System.
"""
from django.contrib import admin
from django.utils.html import format_html
from django.utils.timezone import localtime
from .models import NVR, Camera


class CameraInline(admin.TabularInline):
    model = Camera
    extra = 0
    fields = ('name', 'camera_id', 'channel', 'preview_path', 'is_active')
    readonly_fields = ('created_at',)
    ordering = ('channel', 'name')
    show_change_link = True


@admin.register(NVR)
class NVRAdmin(admin.ModelAdmin):
    list_display  = ['location', 'brand_badge', 'url', 'port', 'status_badge', 'camera_count', 'last_connected', 'created_at']
    list_filter   = ['brand', 'status', 'is_connected']
    search_fields = ['location', 'url', 'username']
    readonly_fields = ['created_at', 'updated_at', 'last_connected', 'status', 'is_connected', 'error_message']
    inlines = [CameraInline]
    fieldsets = (
        ('Device Info', {
            'fields': ('location', 'brand', 'url', 'port', 'notes')
        }),
        ('Credentials', {
            'fields': ('username', 'password'),
            'classes': ('collapse',),
        }),
        ('Status', {
            'fields': ('status', 'is_connected', 'last_connected', 'error_message'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Brand')
    def brand_badge(self, obj):
        colors = {
            'hikvision': '#00d4ff',
            'cpplus':    '#f0b429',
            'dahua':     '#a78bfa',
            'generic':   '#3fb950',
            'unknown':   '#7d8590',
        }
        color = colors.get(obj.brand, '#7d8590')
        return format_html(
            '<span style="background:{};color:#000;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold">{}</span>',
            color, obj.brand.upper()
        )

    @admin.display(description='Status')
    def status_badge(self, obj):
        colors = {'connected': 'green', 'disconnected': 'orange', 'error': 'red', 'pending': 'gray'}
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color:{}">{}</span>', color, obj.status.upper()
        )

    @admin.display(description='Cameras')
    def camera_count(self, obj):
        return obj.cameras.filter(is_active=True).count()


@admin.register(Camera)
class CameraAdmin(admin.ModelAdmin):
    list_display  = ['name', 'nvr_link', 'channel', 'camera_id', 'preview_path_short', 'is_active', 'created_at']
    list_filter   = ['is_active', 'nvr__brand', 'nvr']
    search_fields = ['name', 'camera_id', 'nvr__location']
    readonly_fields = ['created_at', 'updated_at']
    list_select_related = ['nvr']

    @admin.display(description='NVR')
    def nvr_link(self, obj):
        from django.urls import reverse
        url = reverse('admin:core_nvr_change', args=[obj.nvr.id])
        return format_html('<a href="{}">{}</a>', url, obj.nvr.location)

    @admin.display(description='Preview Path')
    def preview_path_short(self, obj):
        path = obj.preview_path or '/'
        return path[:50] + '...' if len(path) > 50 else path
