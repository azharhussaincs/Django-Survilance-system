"""
Database models for the NVR Surveillance System.

Tables:
  - NVR      : Stores NVR device details (location, URL, credentials, brand)
  - Camera   : Stores individual cameras belonging to each NVR
"""

from django.db import models
from django.utils import timezone
from urllib.parse import urlparse, urlunparse


class NVR(models.Model):
    """Represents a single Network Video Recorder device."""

    BRAND_CHOICES = [
        ('hikvision', 'Hikvision'),
        ('cpplus',    'CP Plus'),
        ('dahua',     'Dahua'),
        ('generic',   'Generic'),
        ('unknown',   'Unknown'),
    ]

    STATUS_CHOICES = [
        ('connected',    'Connected'),
        ('disconnected', 'Disconnected'),
        ('error',        'Error'),
        ('pending',      'Pending'),
    ]

    # ── Core fields ───────────────────────────────────────────────────────────
    location    = models.CharField(max_length=255, help_text="Physical/logical location label")
    url         = models.CharField(max_length=500, help_text="Base URL of NVR web interface (e.g. http://192.168.1.100:8080)")
    port        = models.PositiveIntegerField(null=True, blank=True, help_text="Port if not included in URL")
    username    = models.CharField(max_length=150)
    password    = models.CharField(max_length=255)
    brand       = models.CharField(max_length=50, choices=BRAND_CHOICES, default='unknown')

    # ── Status fields ─────────────────────────────────────────────────────────
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    is_connected    = models.BooleanField(default=False)
    last_connected  = models.DateTimeField(null=True, blank=True)
    error_message   = models.TextField(blank=True, default='')

    # ── Meta ──────────────────────────────────────────────────────────────────
    created_at  = models.DateTimeField(default=timezone.now)
    updated_at  = models.DateTimeField(auto_now=True)
    notes       = models.TextField(blank=True, default='', help_text="Optional admin notes")

    class Meta:
        db_table = 'nvr'
        ordering = ['-created_at']
        verbose_name = 'NVR'
        verbose_name_plural = 'NVRs'

    def __str__(self):
        return f"{self.location} [{self.brand}] – {self.url}"

    # ── URL helpers ───────────────────────────────────────────────────────────
    def get_base_url(self):
        """
        Returns the base URL (scheme + host + port) with no path.
        If self.port is set and not already in the URL, it is injected.
        """
        raw = self.url.strip().rstrip('/')
        if not raw.startswith(('http://', 'https://')):
            raw = 'http://' + raw
        try:
            p = urlparse(raw)
            host = p.hostname or ''
            port = p.port or self.port
            if port and port not in (80, 443):
                netloc = f"{host}:{port}"
            else:
                netloc = host
            return urlunparse((p.scheme, netloc, '', '', '', ''))
        except Exception:
            return raw

    def get_full_url(self):
        """Returns the full URL including any path that was stored."""
        raw = self.url.strip()
        if not raw.startswith(('http://', 'https://')):
            raw = 'http://' + raw
        try:
            p = urlparse(raw)
            host = p.hostname or ''
            port = p.port or self.port
            if port and port not in (80, 443):
                netloc = f"{host}:{port}"
            else:
                netloc = host
            return urlunparse((p.scheme, netloc, p.path or '/', '', '', ''))
        except Exception:
            return raw

    def get_camera_count(self):
        return self.cameras.filter(is_active=True).count()

    def mark_connected(self):
        self.is_connected = True
        self.status = 'connected'
        self.last_connected = timezone.now()
        self.error_message = ''
        self.save(update_fields=['is_connected', 'status', 'last_connected', 'error_message', 'updated_at'])

    def mark_error(self, message=''):
        self.is_connected = False
        self.status = 'error'
        self.error_message = message
        self.save(update_fields=['is_connected', 'status', 'error_message', 'updated_at'])


class Camera(models.Model):
    """Represents a single camera channel on an NVR."""

    nvr           = models.ForeignKey(NVR, on_delete=models.CASCADE, related_name='cameras')
    name          = models.CharField(max_length=255)
    camera_id     = models.CharField(max_length=100, blank=True, default='', help_text="Channel ID or camera ID from the NVR")
    preview_path  = models.CharField(max_length=500, blank=True, default='/', help_text="Relative path or full URL to the preview page")
    rtsp_url      = models.CharField(max_length=1000, blank=True, default='', help_text="RTSP stream URL (e.g. rtsp://user:pass@ip:port/ch1)")
    camera_ip     = models.GenericIPAddressField(null=True, blank=True, help_text="Direct IP of the camera if available")
    channel       = models.PositiveIntegerField(null=True, blank=True, help_text="Channel number on NVR")
    is_active     = models.BooleanField(default=True)
    created_at    = models.DateTimeField(default=timezone.now)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'camera'
        ordering = ['nvr', 'channel', 'name']
        verbose_name = 'Camera'
        verbose_name_plural = 'Cameras'
        unique_together = [('nvr', 'camera_id')]

    def __str__(self):
        return f"{self.name} (NVR: {self.nvr.location}, CH{self.channel})"

    def get_preview_url(self):
        """
        Returns full preview URL with embedded credentials.
        """
        from .utils.url_parser import build_auth_url
        path = self.preview_path or '/'
        if path.startswith('http://') or path.startswith('https://'):
            return path
        base = self.nvr.get_base_url()
        path = path if path.startswith('/') else '/' + path
        # Embed username:password@ in the URL
        return build_auth_url(f"{base}{path}", self.nvr.username, self.nvr.password)

    def get_raw_preview_url(self):
        """
        Returns full preview URL WITHOUT embedded credentials.
        Useful if the browser blocks the auth-embedded one.
        """
        path = self.preview_path or '/'
        if path.startswith('http://') or path.startswith('https://'):
            return path
        base = self.nvr.get_base_url()
        path = path if path.startswith('/') else '/' + path
        return f"{base}{path}"

    def to_dict(self):
        return {
            'id':              self.id,
            'name':            self.name,
            'camera_id':       self.camera_id,
            'channel':         self.channel,
            'preview_url':     self.get_preview_url(),
            'raw_preview_url': self.get_raw_preview_url(),
            'rtsp_url':        self.rtsp_url,
            'camera_ip':       self.camera_ip,
            'preview_path':    self.preview_path,
            'is_active':       self.is_active,
        }
