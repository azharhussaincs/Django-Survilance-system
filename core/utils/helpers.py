"""
General helper utilities for the NVR surveillance system.
"""
import logging
import requests
from django.conf import settings

logger = logging.getLogger('core')

CONNECT_TIMEOUT = getattr(settings, 'NVR_CONNECT_TIMEOUT', 15)
READ_TIMEOUT    = getattr(settings, 'NVR_READ_TIMEOUT',    20)


def make_session(username: str = None, password: str = None) -> requests.Session:
    """
    Create and return a pre-configured requests.Session.
    Optionally pre-loads HTTP Basic Auth credentials.
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
    })
    if username and password:
        from requests.auth import HTTPBasicAuth
        session.auth = HTTPBasicAuth(username, password)
    return session


def safe_get(session: requests.Session, url: str, **kwargs) -> requests.Response | None:
    """GET with timeout, returning None on any network error."""
    kwargs.setdefault('timeout', (CONNECT_TIMEOUT, READ_TIMEOUT))
    kwargs.setdefault('verify', False)
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return session.get(url, **kwargs)
    except requests.Timeout:
        logger.warning(f"Timeout GET {url}")
        raise TimeoutError(f"Connection timed out: {url}")
    except requests.ConnectionError as e:
        logger.warning(f"ConnectionError GET {url}: {e}")
        raise ConnectionError(f"Cannot connect to {url}")
    except Exception as e:
        logger.error(f"Error GET {url}: {e}")
        return None


def safe_post(session: requests.Session, url: str, **kwargs) -> requests.Response | None:
    """POST with timeout, returning None on any network error."""
    kwargs.setdefault('timeout', (CONNECT_TIMEOUT, READ_TIMEOUT))
    kwargs.setdefault('verify', False)
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return session.post(url, **kwargs)
    except requests.Timeout:
        raise TimeoutError(f"Connection timed out: {url}")
    except requests.ConnectionError as e:
        raise ConnectionError(f"Cannot connect to {url}")
    except Exception as e:
        logger.error(f"Error POST {url}: {e}")
        return None


def truncate(s: str, length: int = 50) -> str:
    s = str(s)
    return s[:length] + '…' if len(s) > length else s


def check_port(host: str, port: int, timeout: int = 3) -> bool:
    """Check if a TCP port is open."""
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False
