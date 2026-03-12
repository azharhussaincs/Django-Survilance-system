"""
URL parsing, normalization, brand detection, and validation utilities.
"""
import re
import logging
from urllib.parse import urlparse, urlunparse, quote, urlencode

logger = logging.getLogger('core')


# ─────────────────────────────────────────────────────────────────────────────
# Brand detection patterns
# ─────────────────────────────────────────────────────────────────────────────
BRAND_PATTERNS = {
    'hikvision': [
        r'/doc/page/preview\.asp',
        r'/doc/page/login\.asp',
        r'/ISAPI/',
        r'hikvision',
        r'/doc/page/',
    ],
    'cpplus': [
        r'#/index/preview',
        r'cpplus',
        r'cp-plus',
    ],
    'dahua': [
        r'/RPC2',
        r'dahua',
        r'/cgi-bin/configManager\.cgi',
    ],
    'generic': [
        r'/cgi-bin/main-cgi',
        r'/cgi-bin/',
    ],
}

# CP Plus also uses port 20443 as a signal
CPPLUS_PORTS = {20443}


def detect_brand(url: str, port: int = None) -> str:
    """
    Detect the NVR brand from the URL and optional port.

    Priority order: hikvision → cpplus → dahua → generic → unknown
    """
    url_lower = url.lower()

    # Check port-based detection first
    if port and int(port) in CPPLUS_PORTS:
        return 'cpplus'

    # Check parsed port in URL
    try:
        parsed = urlparse(url if url.startswith('http') else 'http://' + url)
        if parsed.port and parsed.port in CPPLUS_PORTS:
            return 'cpplus'
    except Exception:
        pass

    # Check URL patterns
    for brand, patterns in BRAND_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, url_lower):
                return brand

    return 'unknown'


def parse_nvr_url(url: str, port=None) -> dict:
    """
    Parse and normalise an NVR URL. Returns a dict with:
      full_url   - scheme://host:port/path
      base_url   - scheme://host:port   (no path)
      hostname
      port       - int or None
      scheme     - 'http' or 'https'
      path
      is_valid   - bool
      error      - str or ''
    """
    url = url.strip()
    if not url:
        return _invalid('URL is empty.')

    # If scheme is present, we respect it.
    # Otherwise, we'll try to determine it later, but default to http for parsing.
    original_scheme = None
    if url.startswith(('http://', 'https://')):
        original_scheme = url.split('://')[0]
    else:
        url = 'http://' + url

    try:
        p = urlparse(url)
        hostname = p.hostname
        if not hostname:
            return _invalid(f"Cannot parse hostname from: {url}")

        # Determine final port
        final_port = p.port
        if port:
            try:
                explicit_port = int(port)
                if not final_port:
                    final_port = explicit_port
            except (ValueError, TypeError):
                pass

        # Protocol auto-detection logic
        # If user provided a scheme (like https:// or http://), we stick with it.
        # If not, and port is 20443 (CP Plus SSL), we prefer https.
        # If not, we'll try both in the connection stage, but for now we set a default.
        scheme = original_scheme
        if not scheme:
            if final_port == 20443:
                scheme = 'https'
            else:
                scheme = 'http'

        # Build netloc
        if final_port and final_port not in (80, 443):
            netloc = f"{hostname}:{final_port}"
        else:
            netloc = hostname

        path = p.path or '/'

        full_url = urlunparse((scheme, netloc, path, '', '', ''))
        base_url = urlunparse((scheme, netloc, '',   '', '', ''))

        return {
            'full_url':  full_url,
            'base_url':  base_url,
            'hostname':  hostname,
            'port':      final_port,
            'scheme':    scheme,
            'path':      path,
            'is_valid':  True,
            'error':     '',
            'has_explicit_scheme': original_scheme is not None
        }

    except Exception as e:
        return _invalid(str(e))


def _invalid(error: str) -> dict:
    return {
        'full_url': '', 'base_url': '', 'hostname': None,
        'port': None, 'scheme': 'http', 'path': '/',
        'is_valid': False, 'error': error,
        'has_explicit_scheme': False
    }


def auto_detect_protocol(hostname: str, port: int) -> str:
    """
    Try HTTPS then HTTP to see which one is responding.
    Returns 'https' or 'http'.
    """
    import requests
    from .helpers import CONNECT_TIMEOUT
    
    # Common SSL ports or explicit port provided
    protocols = ['https', 'http']
    
    # If it's a known SSL port, try https first.
    # Otherwise, it doesn't hurt to try https first anyway if we're not sure.
    
    for proto in protocols:
        url = f"{proto}://{hostname}:{port}" if port else f"{proto}://{hostname}"
        try:
            logger.debug(f"Auto-detecting protocol: Trying {url}")
            # verify=False because NVRs often have self-signed certs
            resp = requests.get(url, timeout=CONNECT_TIMEOUT, verify=False, stream=True)
            logger.info(f"Protocol detected: {proto} for {hostname}:{port}")
            return proto
        except Exception as e:
            logger.debug(f"Protocol check failed for {url}: {e}")
            continue
            
    return 'http' # Fallback


def validate_nvr_url(url: str) -> list[str]:
    """Return a list of validation error strings (empty = valid)."""
    errors = []
    if not url or not url.strip():
        errors.append('URL cannot be empty.')
        return errors

    result = parse_nvr_url(url)
    if not result['is_valid']:
        errors.append(f"Invalid URL: {result['error']}")
    return errors


def encode_password(password: str) -> str:
    """URL-encode special characters in a password (e.g. @ → %40)."""
    return quote(str(password), safe='')


def build_auth_url(base_url: str, username: str, password: str) -> str:
    """Build a URL with embedded basic auth credentials."""
    password_enc = encode_password(password)
    p = urlparse(base_url)
    netloc = f"{username}:{password_enc}@{p.netloc}"
    return urlunparse((p.scheme, netloc, p.path, p.params, p.query, p.fragment))


def build_rtsp_url(brand: str, hostname: str, port: int, username: str, password: str, channel: int) -> str:
    """
    Build an RTSP URL based on the brand and NVR details.
    
    Hikvision: rtsp://user:pass@ip:port/Streaming/Channels/{channel}01
    Dahua:    rtsp://user:pass@ip:port/cam/realmonitor?channel={channel}&subtype=0
    CP Plus:  rtsp://user:pass@ip:port/cam/realmonitor?channel={channel}&subtype=0
    Generic:  rtsp://user:pass@ip:port/ch{channel}
    """
    user_pass = f"{username}:{encode_password(password)}"
    netloc = f"{hostname}:{port}" if port else hostname
    
    if brand == 'hikvision':
        # channel 1 -> 101, channel 2 -> 201 (main stream)
        hik_ch = f"{channel}01"
        return f"rtsp://{user_pass}@{netloc}/Streaming/Channels/{hik_ch}"
    elif brand in ('dahua', 'cpplus'):
        # For Dahua/CP Plus, try the standard port-based format first
        # Users reported this format working on VLC: rtsp://user:pass@ip:port?channel=2
        # We'll use this as the primary format if discovery was fuzzy
        return f"rtsp://{user_pass}@{netloc}/cam/realmonitor?channel={channel}&subtype=0"
    elif brand == 'generic':
        # Many generic NVRs use this very simple format: rtsp://user:pass@ip:port?channel=2
        return f"rtsp://{user_pass}@{netloc}?channel={channel}"
    else:
        # Some generic NVRs use /ch1/0 (channel 1, main stream)
        return f"rtsp://{user_pass}@{netloc}/Streaming/Channels/{channel}01"
