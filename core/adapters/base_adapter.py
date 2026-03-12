"""
Abstract base class that every NVR adapter must implement.
"""
import abc
import logging

logger = logging.getLogger('core')


class BaseAdapter(abc.ABC):
    """
    Abstract adapter. Subclass for each NVR brand.

    Contract:
      login()         → bool   (True = auth succeeded)
      fetch_cameras() → list[dict]
      preview_url()   → str
      detect(url)     → bool  (classmethod)
    """

    BRAND = 'unknown'

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url  = base_url.rstrip('/')
        self.username  = username
        self.password  = password
        self.logged_in = False
        self._session  = None

    # ── Required interface ────────────────────────────────────────────────────
    @abc.abstractmethod
    def login(self) -> bool:
        """Authenticate against the NVR. Return True on success."""

    def fetch_cameras(self) -> list[dict]:
        """
        Discover cameras using multiple methods in order of preference:
        1. ONVIF
        2. Brand-specific API (implemented in subclass)
        3. Manual RTSP probing
        """
        from urllib.parse import urlparse
        from ..utils.onvif_utils import discover_onvif_cameras, probe_rtsp_channels
        
        p = urlparse(self.base_url)
        host = p.hostname or ''
        port = p.port or 80
        
        # 1. Try ONVIF
        logger.info(f"[{self.BRAND}] Attempting ONVIF discovery for {host}")
        cameras = discover_onvif_cameras(host, port, self.username, self.password)
        
        # If ONVIF found more than 1 camera, it's likely successful
        if len(cameras) > 1:
            logger.info(f"[{self.BRAND}] ONVIF Response: Found {len(cameras)} cameras via ONVIF")
            return cameras
            
        # 2. Try Brand API (subclass must implement _fetch_via_api)
        # We try this even if ONVIF found 0 or 1 camera, as brand APIs often return more detailed channel lists for NVRs.
        logger.info(f"[{self.BRAND}] ONVIF returned {len(cameras)} cameras, attempting brand-specific API discovery")
        try:
            api_cameras = self._fetch_via_api()
            if api_cameras:
                logger.info(f"[{self.BRAND}] API Response: Found {len(api_cameras)} cameras via API")
                # Merge or prefer API if it found more
                if len(api_cameras) >= len(cameras):
                    return api_cameras
                return cameras
        except NotImplementedError:
            logger.debug(f"[{self.BRAND}] _fetch_via_api not implemented")
        except Exception as e:
            logger.error(f"[{self.BRAND}] API Response: Error: {e}")

        if cameras:
            return cameras

        # 3. Try Manual Probing (Fast channel generation, no validation)
        logger.info(f"[{self.BRAND}] API failed, attempting fast RTSP channel discovery (1-16)")
        cameras = probe_rtsp_channels(host, port, self.username, self.password, self.BRAND, max_channels=16)
        if cameras:
            logger.info(f"[{self.BRAND}] RTSP validation Response: Found {len(cameras)} cameras")
            return cameras

        logger.warning(f"[{self.BRAND}] All discovery methods failed for {host}. Real camera count: 0")
        return []

    def _fetch_via_api(self) -> list[dict]:
        """Subclasses should override this for brand-specific API calls."""
        raise NotImplementedError()

    @abc.abstractmethod
    def preview_url(self, channel: int = None) -> str:
        """Return the primary preview page URL for this NVR."""

    @classmethod
    @abc.abstractmethod
    def detect(cls, url: str) -> bool:
        """Return True if the URL looks like this brand."""

    # ── Shared helpers ────────────────────────────────────────────────────────
    def build_rtsp_url(self, channel: int) -> str:
        """
        Build an RTSP URL based on the brand and NVR details.
        
        Hikvision: rtsp://user:pass@ip:port/Streaming/Channels/{channel}01
        Dahua:    rtsp://user:pass@ip:port/cam/realmonitor?channel={channel}&subtype=0
        CP Plus:  rtsp://user:pass@ip:port/cam/realmonitor?channel={channel}&subtype=0
        Generic:  rtsp://user:pass@ip:port/ch{channel}
        """
        from ..utils.url_parser import encode_password, build_rtsp_url
        from urllib.parse import urlparse
        
        p = urlparse(self.base_url)
        hostname = p.hostname or ''
        port = p.port or 554 # Default RTSP port
        
        return build_rtsp_url(self.BRAND, hostname, port, self.username, self.password, channel)

    def _default_cameras(self, count: int = 8) -> list[dict]:
        """Generate placeholder camera entries when real discovery fails."""
        cameras = []
        for i in range(1, count + 1):
            cameras.append({
                'name':         f"Channel {i}",
                'camera_id':    str(i),
                'preview_path': self.preview_url(),
                'channel':      i,
                'rtsp_url':     self.build_rtsp_url(i),
            })
        return cameras

    def _make_session(self):
        from ..utils.helpers import make_session
        if self._session is None:
            self._session = make_session()
        return self._session

    @property
    def session(self):
        return self._make_session()
