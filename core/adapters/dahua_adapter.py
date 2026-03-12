"""
Dahua NVR adapter.

Detection: /RPC2  or  'dahua' in URL
Login:     Digest auth (WSSE) → Basic auth → Form POST
Preview:   /RPC_Loadfile/vh264/ch{N}/sub/av_stream  or /
"""
import hashlib
import logging
import json
from requests.auth import HTTPDigestAuth, HTTPBasicAuth
from bs4 import BeautifulSoup

from .base_adapter import BaseAdapter
from ..utils.helpers import safe_get, safe_post

logger = logging.getLogger('core')


class DahuaAdapter(BaseAdapter):

    BRAND        = 'dahua'
    PREVIEW_PATH = '/'

    @classmethod
    def detect(cls, url: str) -> bool:
        url_lower = url.lower()
        return any(p in url_lower for p in ['dahua', '/rpc2', '/cgi-bin/configmanager.cgi'])

    def login(self) -> bool:
        # 1. Digest auth
        try:
            resp = safe_get(self.session, self.base_url,
                            auth=HTTPDigestAuth(self.username, self.password))
            if resp and resp.status_code == 200:
                self.logged_in = True
                logger.info(f"[Dahua] Digest auth OK – {self.base_url}")
                return True
        except (TimeoutError, ConnectionError):
            raise
        except Exception as e:
            logger.debug(f"[Dahua] Digest failed: {e}")

        # 2. Basic auth
        try:
            resp = safe_get(self.session, self.base_url,
                            auth=HTTPBasicAuth(self.username, self.password))
            if resp and resp.status_code == 200:
                self.logged_in = True
                logger.info(f"[Dahua] Basic auth OK – {self.base_url}")
                return True
        except (TimeoutError, ConnectionError):
            raise
        except Exception as e:
            logger.debug(f"[Dahua] Basic auth failed: {e}")

        # 3. RPC2 login
        try:
            url  = f"{self.base_url}/RPC2_Login"
            body = {
                "method": "global.login",
                "params": {
                    "userName": self.username,
                    "password": "",
                    "clientType": "Web3.0",
                    "authorityType": "Default",
                },
                "id": 1
            }
            resp = safe_post(self.session, url, json=body)
            if resp and resp.status_code == 200:
                data = resp.json()
                realm    = data.get('params', {}).get('realm', '')
                random   = data.get('params', {}).get('random', '')
                ha1 = hashlib.md5(f"{self.username}:{realm}:{self.password}".encode()).hexdigest()
                ha2 = hashlib.md5(f"{self.username}:{random}:{ha1}".encode()).hexdigest()
                body2 = {
                    "method": "global.login",
                    "params": {
                        "userName": self.username,
                        "password": ha2,
                        "clientType": "Web3.0",
                        "authorityType": "Default",
                        "loginType": "Direct",
                    },
                    "session": data.get("session"),
                    "id": 2,
                }
                resp2 = safe_post(self.session, url, json=body2)
                if resp2 and resp2.json().get('result'):
                    self.logged_in = True
                    logger.info(f"[Dahua] RPC2 login OK – {self.base_url}")
                    return True
        except (TimeoutError, ConnectionError):
            raise
        except Exception as e:
            logger.debug(f"[Dahua] RPC2 login failed: {e}")

        return False

    def _fetch_via_api(self) -> list[dict]:
        cameras = []
        try:
            url  = f"{self.base_url}/cgi-bin/devVideoInput.cgi?action=getCollect"
            # Try both Digest and Basic auth
            for auth_method in [HTTPDigestAuth, HTTPBasicAuth]:
                resp = safe_get(self.session, url, auth=auth_method(self.username, self.password))
                if resp and resp.status_code == 200:
                    lines = resp.text.strip().split('\n')
                    for i, line in enumerate(lines):
                        name = line.split('=')[-1].strip() if '=' in line else f"Channel {i+1}"
                        ch_num = i + 1
                        cameras.append({
                            'name':         name or f"Channel {ch_num}",
                            'camera_id':    str(ch_num),
                            'preview_path': '/',
                            'channel':      ch_num,
                            'rtsp_url':     self.build_rtsp_url(ch_num),
                        })
                    break # Found them
        except Exception as e:
            logger.debug(f"[Dahua] fetch via API failed: {e}")

        return cameras

    def preview_url(self, channel: int = None) -> str:
        """Return a URL with basic auth embedded if it helps bypass login screens."""
        from ..utils.url_parser import build_auth_url
        return build_auth_url(self.base_url + '/', self.username, self.password)
