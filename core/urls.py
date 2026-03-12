"""
URL patterns for the core app (NVR Surveillance System).
"""
from django.urls import path
from . import views

# No app_name to allow global URL namespacing in templates
# app_name = 'core'

urlpatterns = [
    # ── Auth ──────────────────────────────────────────────────────────────────
    path('',        views.login_view,  name='login'),
    path('login/',  views.login_view,  name='login'),
    path('logout/', views.logout_view, name='logout'),

    # ── Main UI ───────────────────────────────────────────────────────────────
    path('dashboard/', views.dashboard_view, name='dashboard'),

    # ── NVR API (AJAX) ────────────────────────────────────────────────────────
    path('nvr/connect/',          views.api_connect_nvr,  name='api_connect_nvr'),
    path('nvr/save/',             views.api_save_nvr,     name='api_save_nvr'),
    path('nvr/delete/<int:nvr_id>/', views.api_delete_nvr, name='api_delete_nvr'),

    # ── Camera API (AJAX) ─────────────────────────────────────────────────────
    path('nvr/sync/<int:nvr_id>/',          views.api_sync_nvr,     name='api_sync_nvr'),
    path('camera/delete/<int:camera_id>/', views.api_delete_camera, name='api_delete_camera'),

    # ── List APIs ─────────────────────────────────────────────────────────────
    path('api/nvrs/',                        views.api_list_nvrs,    name='api_list_nvrs'),
    # ── Streaming ─────────────────────────────────────────────────────────────
    path('camera/stream/<int:camera_id>/', views.camera_stream_view, name='camera_stream'),
]
