"""
Generic / fallback NVR adapter.

Tries every known auth method and login path in sequence.
Always returns something useful (defaults if needed).
"""
import logging
from bs4 import BeautifulSoup
from requests.auth import HTTPDigestAuth, HTTPBasicAuth

from .base_adapter import BaseAdapter
from ..utils.helpers import safe_get, safe_post

logger = logging.getLogger('core')


class GenericAdapter(BaseAdapter):

    BRAND = 'generic'

    LOGIN_PATHS = [
        '/login', '/cgi-bin/login.cgi', '/web/login',
        '/cgi-bin/main-cgi', '/index.html', '/login.html',
        '/login.asp', '/logon', '/', '/doc/page/login.asp',
        '/web/login.html', '/index.php', '/lane/qualixadmin/TRHA/',
    ]

    PREVIEW_PATHS = [
        '/cgi-bin/main-cgi', '/live', '/preview', '/monitor',
        '/video', '/stream', '/channel', '/', '/live/index.html',
        '/doc/page/preview.asp', '/cgi-bin/snapshot.cgi',
        '/cgi-bin/snapshot.cgi?channel=1', '/web/live.html',
        '/live.html', '/liveview', '/index.html', '/#live',
        '/web/index.html', '/web/preview.html', '/view.html',
        '/doc/page/preview.html', '/mobile/index.html',
        '/api/v1/preview', '/api/video/channels',
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._preview_path = '/'

    # ── Detection ─────────────────────────────────────────────────────────────
    @classmethod
    def detect(cls, url: str) -> bool:
        """Generic always matches as fallback."""
        return True

    # ── Login ─────────────────────────────────────────────────────────────────
    def login(self) -> bool:
        """
        Order:
        1. Fast check if any path is reachable
        2. Digest auth on each preview path
        3. Basic auth on each preview path
        4. Form-based POST on each login path
        """
        from ..utils.helpers import check_port
        from urllib.parse import urlparse
        
        p = urlparse(self.base_url)
        host = p.hostname or ''
        port = p.port or (80 if p.scheme == 'http' else 443)
        
        # Fast TCP check before hammering with requests
        if not check_port(host, port, timeout=2):
            logger.warning(f"[Generic] Host {host}:{port} not reachable via TCP. Skipping web auth.")
            self.logged_in = True # Still allow discovery to proceed (ONVIF/RTSP)
            return True

        # 1. Digest auth (only first 3 paths for speed)
        for path in self.PREVIEW_PATHS[:3]:
            try:
                url  = f"{self.base_url}{path}"
                resp = safe_get(self.session, url,
                                auth=HTTPDigestAuth(self.username, self.password),
                                timeout=(3, 5))
                if resp and resp.status_code == 200:
                    self._preview_path = path
                    self.logged_in = True
                    logger.info(f"[Generic] Digest auth OK at {url}")
                    return True
            except (TimeoutError, ConnectionError):
                continue # Try next path or method instead of failing entire NVR
            except Exception:
                pass

        # 2. Basic auth (only first 3 paths for speed)
        for path in self.PREVIEW_PATHS[:3]:
            try:
                url  = f"{self.base_url}{path}"
                resp = safe_get(self.session, url,
                                auth=HTTPBasicAuth(self.username, self.password),
                                timeout=(3, 5))
                if resp and resp.status_code == 200:
                    self._preview_path = path
                    self.logged_in = True
                    logger.info(f"[Generic] Basic auth OK at {url}")
                    return True
            except (TimeoutError, ConnectionError):
                continue
            except Exception:
                pass

        # 3. Form-based login
        for login_path in self.LOGIN_PATHS:
            try:
                login_url = f"{self.base_url}{login_path}"
                get_resp  = safe_get(self.session, login_url)
                if not get_resp or get_resp.status_code != 200:
                    continue

                # Try to detect form action
                soup = BeautifulSoup(get_resp.text, 'html.parser')
                form = soup.find('form')
                action_url = login_url
                if form and form.get('action'):
                    action = form['action'].strip()
                    if action.startswith('http'):
                        action_url = action
                    elif action:
                        action_url = f"{self.base_url}/{action.lstrip('/')}"

                resp = safe_post(self.session, action_url, data={
                    'username': self.username, 'user':     self.username,
                    'password': self.password, 'pass':     self.password,
                    'passwd':   self.password, 'pwd':      self.password,
                })
                if resp and resp.status_code in (200, 302):
                    self._preview_path = login_path
                    self.logged_in = True
                    logger.info(f"[Generic] Form login OK at {action_url}")
                    return True
            except (TimeoutError, ConnectionError):
                raise
            except Exception:
                pass

        # If everything fails, still mark as "connected" so the iframe can be shown
        logger.warning(f"[Generic] All auth methods failed for {self.base_url} – embedding anyway")
        self.logged_in = True
        return True

    # ── Camera discovery ──────────────────────────────────────────────────────
    def _fetch_via_api(self) -> list[dict]:
        """Attempt to discover cameras via APIs or HTML scraping."""
        cameras = self._try_api_discovery()
        if cameras:
            return cameras

        for path in self.PREVIEW_PATHS:
            cameras = self._scrape_preview(path)
            if cameras:
                self._preview_path = path
                logger.info(f"[Generic] Discovered {len(cameras)} cameras at {path}")
                return cameras

        return []

    def _try_rtsp_discovery(self) -> list[dict]:
        """Try to detect cameras by probing the RTSP port."""
        from ..utils.helpers import check_port
        from urllib.parse import urlparse
        
        p = urlparse(self.base_url)
        hostname = p.hostname or ''
        
        # If RTSP port is open, assume at least some cameras exist
        if check_port(hostname, 554):
            logger.info(f"[Generic] RTSP port 554 is open, generating 8 channels")
            return self._default_cameras(8)
        return []

    # ── Preview URL ───────────────────────────────────────────────────────────
    def _try_api_discovery(self) -> list[dict]:
        """Try common NVR API endpoints for camera discovery."""
        endpoints = [
            ('/ISAPI/System/Video/inputs/channels', 'xml'),
            ('/cgi-bin/configManager.cgi?action=getConfig&name=VideoInChannel', 'text'),
            ('/RPC2', 'json'),
            ('/onvif/device_service', 'xml'),
        ]
        
        for path, fmt in endpoints:
            try:
                url = f"{self.base_url}{path}"
                # Try Digest first then Basic
                resp = safe_get(self.session, url, auth=HTTPDigestAuth(self.username, self.password))
                if not resp or resp.status_code != 200:
                    resp = safe_get(self.session, url, auth=HTTPBasicAuth(self.username, self.password))
                
                if resp and resp.status_code == 200:
                    logger.info(f"[Generic] API discovery success at {path}")
                    # Basic parser based on format
                    if fmt == 'xml':
                        soup = BeautifulSoup(resp.text, 'xml')
                        items = soup.find_all(['VideoInputChannel', 'Channel', 'Device'])
                        if items:
                            cameras = []
                            for i, item in enumerate(items):
                                ch_id = item.find('id') or item.find('ChannelID')
                                name = item.find('name') or item.find('channelName')
                                idx = ch_id.get_text(strip=True) if ch_id else str(i+1)
                                cameras.append({
                                    'name': name.get_text(strip=True) if name else f"Camera {idx}",
                                    'camera_id': idx,
                                    'preview_path': self._preview_path,
                                    'channel': int(idx) if idx.isdigit() else i+1,
                                    'rtsp_url': self.build_rtsp_url(int(idx) if idx.isdigit() else i+1),
                                })
                            return cameras
            except Exception as e:
                logger.debug(f"[Generic] API discovery failed at {path}: {e}")
        return []

    def _scrape_preview(self, path: str) -> list[dict]:
        """Scrape a specific preview page for cameras."""
        cameras = []
        try:
            url = f"{self.base_url}{path}"
            resp = safe_get(self.session, url)
            if not resp or resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, 'html.parser')

            # Look for video/img/iframe/div elements hinting at cameras
            candidates = (
                soup.find_all('video') +
                soup.find_all('iframe') +
                soup.find_all('embed') +
                soup.find_all('object') +
                soup.find_all(attrs=lambda a: a and any(
                    k in str(a).lower() for k in
                    ['channel', 'cam', 'stream', 'live', 'preview', 'monitor', 'viewport', 'screen']
                ))
            )
            seen = set()
            for i, el in enumerate(candidates[:24]):
                # Attempt to extract a more specific path if possible
                # e.g. from an iframe src
                el_path = path
                if el.name == 'iframe' and el.get('src'):
                    src = el.get('src')
                    if src.startswith('/'):
                        el_path = src
                    elif '://' not in src:
                        el_path = f"{path.rstrip('/')}/{src.lstrip('/')}"

                key = el.get('id') or el.get('src') or str(i)
                if key in seen:
                    continue
                seen.add(key)
                name = (
                    el.get('title') or
                    el.get('data-name') or
                    el.get_text(strip=True) or
                    el.get('alt') or
                    f"Camera {len(cameras)+1}"
                )
                ch_num = len(cameras) + 1
                cameras.append({
                    'name':         str(name)[:60],
                    'camera_id':    str(ch_num),
                    'preview_path': el_path,
                    'channel':      ch_num,
                    'rtsp_url':     self.build_rtsp_url(ch_num),
                })
        except Exception as e:
            logger.debug(f"[Generic] Scrape failed at {path}: {e}")
        return cameras

    def preview_url(self, channel: int = None) -> str:
        """Embed auth in URL for the best chance of bypassing login screens."""
        from ..utils.url_parser import build_auth_url
        path = getattr(self, '_preview_path', '/')
        return build_auth_url(f"{self.base_url}{path}", self.username, self.password)
