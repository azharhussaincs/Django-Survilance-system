"""
CP Plus NVR adapter.

Detection: #/index/preview  or  port 20443
Login:     JSON API → Form POST → Basic auth
Preview:   #/index/preview  (SPA hash route, served as iframe)
"""
import json
import logging
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth

from .base_adapter import BaseAdapter
from ..utils.helpers import safe_get, safe_post

logger = logging.getLogger('core')


class CpPlusAdapter(BaseAdapter):

    BRAND        = 'cpplus'
    PREVIEW_HASH = '#/index/preview'

    LOGIN_ENDPOINTS = [
        '/api/v1/login',
        '/login',
        '/cgi-bin/login.cgi',
        '/api/login',
        '/web/login',
    ]

    CAMERA_ENDPOINTS = [
        '/api/v1/cameras',
        '/api/cameras',
        '/cgi-bin/cameras.cgi',
        '/api/v1/channels',
    ]

    # ── Detection ─────────────────────────────────────────────────────────────
    @classmethod
    def detect(cls, url: str) -> bool:
        url_lower = url.lower()
        if '#/index/preview' in url_lower:
            return True
        if 'cpplus' in url_lower or 'cp-plus' in url_lower:
            return True
        try:
            from urllib.parse import urlparse
            p = urlparse(url if url.startswith('http') else 'http://' + url)
            if p.port == 20443:
                return True
        except Exception:
            pass
        return False

    # ── Login ─────────────────────────────────────────────────────────────────
    def login(self) -> bool:
        """Try JSON API → form POST → basic auth in order."""

        # 1. JSON API login
        for endpoint in self.LOGIN_ENDPOINTS:
            try:
                url  = f"{self.base_url}{endpoint}"
                resp = safe_post(self.session, url, json={
                    'username': self.username,
                    'password': self.password,
                })
                if resp and resp.status_code == 200:
                    try:
                        data = resp.json()
                        token = data.get('token') or data.get('access_token')
                        if token:
                            self.session.headers['Authorization'] = f"Bearer {token}"
                            logger.info(f"[CPPlus] JSON API login OK, token acquired – {self.base_url}")
                    except Exception:
                        pass
                    self.logged_in = True
                    logger.info(f"[CPPlus] JSON login OK – {endpoint}")
                    return True
            except (TimeoutError, ConnectionError):
                raise
            except Exception as e:
                logger.debug(f"[CPPlus] JSON login {endpoint} failed: {e}")

        # 2. Form POST login
        for endpoint in self.LOGIN_ENDPOINTS:
            try:
                url = f"{self.base_url}{endpoint}"
                safe_get(self.session, url)   # GET for cookies
                resp = safe_post(self.session, url, data={
                    'username': self.username,
                    'password': self.password,
                    'user':     self.username,
                    'pass':     self.password,
                })
                if resp and resp.status_code in (200, 302):
                    self.logged_in = True
                    logger.info(f"[CPPlus] Form login OK – {endpoint}")
                    return True
            except (TimeoutError, ConnectionError):
                raise
            except Exception as e:
                logger.debug(f"[CPPlus] Form login {endpoint} failed: {e}")

        # 3. Basic auth
        try:
            resp = safe_get(self.session, self.base_url,
                            auth=HTTPBasicAuth(self.username, self.password))
            if resp and resp.status_code == 200:
                self.logged_in = True
                logger.info(f"[CPPlus] Basic auth OK – {self.base_url}")
                return True
        except (TimeoutError, ConnectionError):
            raise
        except Exception as e:
            logger.debug(f"[CPPlus] Basic auth failed: {e}")

        logger.warning(f"[CPPlus] All login methods failed – {self.base_url}")
        return False

    # ── Camera discovery ──────────────────────────────────────────────────────
    def _fetch_via_api(self) -> list[dict]:
        cameras = []

        # Try JSON API endpoints
        for endpoint in self.CAMERA_ENDPOINTS:
            try:
                url  = f"{self.base_url}{endpoint}"
                resp = safe_get(self.session, url)
                if not resp or resp.status_code != 200:
                    continue
                data = resp.json()
                if isinstance(data, list):
                    for i, cam in enumerate(data):
                        ch_num = int(cam.get('channel') or cam.get('id') or i + 1)
                        cameras.append({
                            'name':         cam.get('name') or cam.get('channelName') or f"Camera {ch_num}",
                            'camera_id':    str(cam.get('id') or cam.get('channel') or ch_num),
                            'preview_path': self.preview_url(),
                            'channel':      ch_num,
                            'rtsp_url':     self.build_rtsp_url(ch_num),
                        })
                    if cameras:
                        logger.info(f"[CPPlus] Found {len(cameras)} cameras via API")
                        return cameras
                elif isinstance(data, dict):
                    items = data.get('cameras') or data.get('channels') or data.get('data') or []
                    for i, cam in enumerate(items):
                        ch_num = int(cam.get('channel') or cam.get('id') or i + 1)
                        cameras.append({
                            'name':         cam.get('name') or f"Camera {ch_num}",
                            'camera_id':    str(cam.get('id') or ch_num),
                            'preview_path': self.preview_url(),
                            'channel':      ch_num,
                            'rtsp_url':     self.build_rtsp_url(ch_num),
                        })
                    if cameras:
                        return cameras
            except Exception as e:
                logger.debug(f"[CPPlus] API {endpoint} parse failed: {e}")

        # Scrape HTML
        cameras = self._scrape_html()
        return cameras

    def _scrape_html(self) -> list[dict]:
        cameras = []
        try:
            resp = safe_get(self.session, self.base_url)
            if not resp or resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, 'html.parser')
            for i, el in enumerate(soup.find_all(attrs={'data-channel': True})[:16]):
                ch_num = int(el.get('data-channel', i + 1))
                cameras.append({
                    'name':         el.get_text(strip=True) or f"Camera {ch_num}",
                    'camera_id':    str(ch_num),
                    'preview_path': self.preview_url(),
                    'channel':      ch_num,
                    'rtsp_url':     self.build_rtsp_url(ch_num),
                })
        except Exception as e:
            logger.debug(f"[CPPlus] HTML scrape failed: {e}")
        return cameras

    # ── Preview URL ───────────────────────────────────────────────────────────
    def preview_url(self, channel: int = None) -> str:
        """Return the primary preview page URL, often an SPA route."""
        # Use basic auth embedding as a hint for the iframe/new tab
        from ..utils.url_parser import build_auth_url
        return build_auth_url(self.base_url + '/', self.username, self.password)
