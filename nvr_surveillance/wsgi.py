"""
WSGI config for NVR Surveillance System.
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nvr_surveillance.settings')
application = get_wsgi_application()
