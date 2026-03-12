"""
Hikvision NVR adapter.

Detection: /doc/page/preview.asp  or  /doc/page/login.asp
Login:     Digest auth → Basic auth → Form-based login
Preview:   /doc/page/preview.asp
"""
import logging
from bs4 import BeautifulSoup
from requests.auth import HTTPDigestAuth, HTTPBasicAuth

from .base_adapter import BaseAdapter
from ..utils.helpers import safe_get, safe_post

logger = logging.getLogger('core')


class HikvisionAdapter(BaseAdapter):

    BRAND        = 'hikvision'
    LOGIN_PATH   = '/doc/page/login.asp'
    PREVIEW_PATHS = [
        '/doc/page/preview.asp',
        '/doc/page/login.asp',
        '/',
        '/index.asp',
        '/preview.asp',
        '/doc/page/preview.asp?_1761543184939&page=preview',
        '/doc/page/preview.html',
        '/web/index.html',
        '/doc/page/live.html',
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.PREVIEW_PATH = '/doc/page/preview.asp'

    # ── Detection ─────────────────────────────────────────────────────────────
    @classmethod
    def detect(cls, url: str) -> bool:
        url_lower = url.lower()
        return any(p in url_lower for p in [
            '/doc/page/preview.asp',
            '/doc/page/login.asp',
            '/doc/page/',
            'hikvision',
            'isapi',
        ])

    # ── Login ─────────────────────────────────────────────────────────────────
    def login(self) -> bool:
        """
        Try three methods in order:
        1. HTTP Digest Auth
        2. HTTP Basic Auth
        3. Form-based POST to login page
        """
        # We try multiple common preview paths to find one that works (200 OK)
        for path in self.PREVIEW_PATHS:
            preview_url = f"{self.base_url}{path}"
            # 1. Digest auth (most common for Hikvision)
            try:
                resp = safe_get(
                    self.session, preview_url,
                    auth=HTTPDigestAuth(self.username, self.password),
                )
                if resp and resp.status_code == 200 and 'login' not in resp.url.lower():
                    self.logged_in = True
                    self.PREVIEW_PATH = path
                    logger.info(f"[Hikvision] Digest auth OK at {path} – {self.base_url}")
                    return True
            except (TimeoutError, ConnectionError):
                raise
            except Exception as e:
                logger.debug(f"[Hikvision] Digest auth at {path} failed: {e}")

            # 2. Basic auth
            try:
                resp = safe_get(
                    self.session, preview_url,
                    auth=HTTPBasicAuth(self.username, self.password),
                )
                if resp and resp.status_code == 200:
                    self.logged_in = True
                    self.PREVIEW_PATH = path
                    logger.info(f"[Hikvision] Basic auth OK at {path} – {self.base_url}")
                    return True
            except (TimeoutError, ConnectionError):
                raise
            except Exception as e:
                logger.debug(f"[Hikvision] Basic auth at {path} failed: {e}")

        # 3. Form-based POST login
        try:
            login_url = f"{self.base_url}{self.LOGIN_PATH}"
            safe_get(self.session, login_url)   # GET first (for cookies / CSRF)

            # Encode password for special chars
            from ..utils.url_parser import encode_password
            resp = safe_post(self.session, login_url, data={
                'username': self.username,
                'password': encode_password(self.password),
                'encoded':  f"{self.username}:{encode_password(self.password)}",
            })
            if resp and resp.status_code in (200, 302):
                self.logged_in = True
                logger.info(f"[Hikvision] Form login OK – {self.base_url}")
                return True
        except (TimeoutError, ConnectionError):
            raise
        except Exception as e:
            logger.debug(f"[Hikvision] Form login failed: {e}")

        logger.warning(f"[Hikvision] All login methods failed for {self.base_url}")
        return False

    # ── Camera discovery ──────────────────────────────────────────────────────
    def _fetch_via_api(self) -> list[dict]:
        """Fetch cameras using Hikvision ISAPI or fallback to scraping."""
        if not self.logged_in:
            if not self.login():
                return []

        # Try ISAPI with common paths
        isapi_paths = [
            "/ISAPI/Streaming/channels",
            "/ISAPI/System/Video/inputs/channels",
            "/ISAPI/ContentMgmt/InputProxy/channels",
            "/ISAPI/ContentMgmt/InputProxy/channels/status",
            "/ISAPI/ContentMgmt/InputProxy/channels/capabilities",
            "/ISAPI/System/Video/inputs/channels/capabilities",
            "/ISAPI/Streaming/channels/capabilities",
        ]
        
        all_cameras = []
        seen_channels = set()
        
        # Check all possible ISAPI paths to gather a complete list of cameras
        for path in isapi_paths:
            isapi_cams = self._try_isapi(path)
            for cam in isapi_cams:
                ch_id = cam['camera_id']
                # Track unique IDs and combine info from different endpoints
                if ch_id not in seen_channels:
                    all_cameras.append(cam)
                    seen_channels.add(ch_id)
                else:
                    # If we already have this channel but found a better name
                    for existing in all_cameras:
                        if existing['camera_id'] == ch_id:
                            # Update name if better
                            if "Channel" in existing['name'] and "Channel" not in cam['name']:
                                existing['name'] = cam['name']
                            # Update rtsp_url if we found a better one (from /Streaming/channels)
                            if not existing.get('rtsp_url') and cam.get('rtsp_url'):
                                existing['rtsp_url'] = cam['rtsp_url']
                            break
        
        if all_cameras:
            # Sort by channel number
            all_cameras.sort(key=lambda x: x['channel'])
            return all_cameras

        # Fallback: scrape the preview page
        cameras = self._scrape_preview()
        if cameras:
            return cameras

        return []

    def _try_isapi(self, path: str = "/ISAPI/System/Video/inputs/channels") -> list[dict]:
        """Try to fetch channel list via Hikvision ISAPI."""
        cameras = []
        try:
            url = f"{self.base_url}{path}"
            # Try Digest then Basic
            resp = safe_get(self.session, url, auth=HTTPDigestAuth(self.username, self.password))
            if not resp or resp.status_code != 200:
                resp = safe_get(self.session, url, auth=HTTPBasicAuth(self.username, self.password))
            
            if not resp or resp.status_code != 200:
                return []
            
            soup = BeautifulSoup(resp.text, 'xml')
            
            # StreamingChannel, VideoInputChannel, InputProxyChannel, InputProxyChannelStatus
            nodes = soup.find_all(['VideoInputChannel', 'StreamingChannel', 'InputProxyChannel', 'InputProxyChannelStatus', 'InputProxyChannelCapability', 'VideoInputChannelCapability'])
            
            for ch in nodes:
                ch_id   = ch.find(['id', 'channelID', 'id'])
                ch_name = ch.find(['name', 'channelName', 'name'])
                
                if not ch_id:
                    # Look in parent or other sibling tags
                    ch_id = ch.find_parent().find('id') if ch.find_parent() else None
                
                if not ch_id:
                    continue
                    
                idx = ch_id.get_text(strip=True)
                
                # Check if we already added this one in this specific call
                if any(c['camera_id'] == idx for c in cameras):
                    continue
                
                # ISAPI channel IDs like 101, 201 are usually MainStreams for ch 1, 2...
                # We want to extract the base channel number.
                if idx.isdigit():
                    val = int(idx)
                    if val > 100:
                        ch_num = val // 100
                    else:
                        ch_num = val
                else:
                    ch_num = len(cameras) + 1
                
                name = ch_name.get_text(strip=True) if ch_name else f"Channel {ch_num}"
                
                # For StreamingChannel, check if it is a main stream (ending in 01 or equivalent)
                # Hikvision usually has 101, 102 (main, sub for ch 1)
                # We only want to add the main stream once per channel.
                if path == "/ISAPI/Streaming/channels" and idx.isdigit():
                    if not idx.endswith('01') and int(idx) > 100:
                        continue # Skip substreams
                
                cameras.append({
                    'name':         name,
                    'camera_id':    idx,
                    'preview_path': self.PREVIEW_PATH,
                    'channel':      ch_num,
                    'rtsp_url':     self.build_rtsp_url(ch_num),
                })
        except Exception as e:
            logger.debug(f"[Hikvision] ISAPI fetch failed at {path}: {e}")
        return cameras

    def _scrape_preview(self) -> list[dict]:
        """Parse the preview page HTML for channel entries."""
        cameras = []
        try:
            url  = f"{self.base_url}{self.PREVIEW_PATH}"
            resp = safe_get(self.session, url,
                            auth=HTTPDigestAuth(self.username, self.password))
            if not resp or resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, 'html.parser')
            candidates = soup.find_all(
                attrs=lambda a: a and any(
                    k in str(a).lower() for k in ['channel', 'cam', 'stream', 'preview']
                )
            )
            for i, el in enumerate(candidates[:16]):
                name = el.get_text(strip=True) or f"Camera {i+1}"
                ch_num = i + 1
                cameras.append({
                    'name':         name[:60],
                    'camera_id':    el.get('id') or el.get('data-ch') or str(ch_num),
                    'preview_path': self.PREVIEW_PATH,
                    'channel':      ch_num,
                    'rtsp_url':     self.build_rtsp_url(ch_num),
                })
        except Exception as e:
            logger.debug(f"[Hikvision] Preview scrape failed: {e}")
        return cameras

    # ── Preview URL ───────────────────────────────────────────────────────────
    def preview_url(self, channel: int = None) -> str:
        """Return a URL with basic auth embedded if it helps bypass login screens in some browsers."""
        from ..utils.url_parser import build_auth_url
        base = self.base_url
        path = getattr(self, 'PREVIEW_PATH', '/doc/page/preview.asp')
        # Some newer browsers block user:pass@host in iframes. 
        # We can offer both or just the raw one if preferred.
        return build_auth_url(f"{base}{path}", self.username, self.password)
