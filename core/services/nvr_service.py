"""
NVR Service Layer – orchestrates brand detection, adapter selection,
login, camera fetching, and database persistence.
"""
import logging
from django.conf import settings
from django.utils import timezone

from ..adapters import HikvisionAdapter, CpPlusAdapter, DahuaAdapter, GenericAdapter
from ..utils.url_parser import detect_brand, parse_nvr_url, auto_detect_protocol

logger = logging.getLogger('core')

# Brand → Adapter mapping (order matters for detection priority)
ADAPTER_MAP = {
    'hikvision': HikvisionAdapter,
    'cpplus':    CpPlusAdapter,
    'dahua':     DahuaAdapter,
    'generic':   GenericAdapter,
    'unknown':   GenericAdapter,
}


def get_adapter(brand: str, base_url: str, username: str, password: str):
    """Instantiate the correct adapter for the given brand."""
    adapter_cls = ADAPTER_MAP.get(brand, GenericAdapter)
    logger.debug(f"Using adapter: {adapter_cls.__name__} for brand '{brand}'")
    return adapter_cls(base_url, username, password)


def connect_nvr(url: str, port, username: str, password: str) -> dict:
    """
    Full connection flow:
      1. Parse & validate URL (with protocol auto-detection)
      2. Detect NVR brand
      3. Instantiate adapter
      4. Login
      5. Fetch cameras (validated RTSP/ONVIF)

    Returns:
      {
        success: bool,
        brand: str,
        base_url: str,
        cameras: list[dict],
        camera_count: int,
        error: str | None,
      }
    """
    result = {
        'success':      False,
        'brand':        'unknown',
        'base_url':     '',
        'cameras':      [],
        'camera_count': 0,
        'error':        None,
    }

    # ── 1. Parse URL ──────────────────────────────────────────────────────────
    parsed = parse_nvr_url(url, port)
    if not parsed['is_valid']:
        result['error'] = parsed.get('error') or f"Invalid URL: {url}"
        return result

    hostname = parsed['hostname']
    final_port = parsed.get('port')
    
    # Protocol auto-detection if no scheme provided
    if not parsed.get('has_explicit_scheme'):
        logger.info(f"No protocol specified for {hostname}. Auto-detecting HTTPS/HTTP...")
        scheme = auto_detect_protocol(hostname, final_port)
        # Update base_url with detected scheme
        from urllib.parse import urlunparse
        netloc = f"{hostname}:{final_port}" if final_port and final_port not in (80, 443) else hostname
        base_url = urlunparse((scheme, netloc, '', '', '', ''))
        logger.info(f"Protocol auto-detected: {scheme}. Using base_url: {base_url}")
    else:
        base_url = parsed['base_url']
        logger.info(f"Using explicit protocol: {parsed['scheme']} for {base_url}")

    result['base_url'] = base_url

    # ── 2. Brand detection ────────────────────────────────────────────────────
    brand = detect_brand(base_url, final_port)
    result['brand'] = brand
    logger.info(f"Detected brand '{brand}' for URL: {base_url}")

    # ── 3 + 4. Adapter + login ────────────────────────────────────────────────
    from ..utils.helpers import check_port
    http_port = final_port or (80 if parsed['scheme'] == 'http' else 443)
    
    logger.info(f"Checking connectivity to {hostname} on port {http_port}...")
    if not check_port(hostname, http_port):
        # We don't return here because some NVRs might only have RTSP (554) open, 
        # though usually they have a web interface.
        logger.warning(f"NVR web interface at {hostname}:{http_port} is not reachable via TCP. Attempting connection anyway.")
    
    adapter = get_adapter(brand, base_url, username, password)
    try:
        ok = adapter.login()
        if not ok:
            # If login fails, we still try to fetch cameras (maybe via ONVIF/RTSP probe which have their own auth)
            logger.warning("Web login failed. Continuing to camera discovery (ONVIF/RTSP)...")
    except TimeoutError as e:
        logger.error(f"Web connection timed out: {e}. Continuing to camera discovery (ONVIF/RTSP)...")
    except ConnectionError as e:
        logger.error(f"Web connection failed: {e}. Continuing to camera discovery (ONVIF/RTSP)...")
    except Exception as e:
        logger.error(f"Web login error: {e}. Continuing to camera discovery (ONVIF/RTSP)...")

    # ── 5. Fetch cameras ──────────────────────────────────────────────────────
    try:
        logger.info(f"Starting camera discovery for {hostname}...")
        cameras = adapter.fetch_cameras()
        
        if not cameras:
            logger.warning(f"No cameras discovered for {hostname} after all methods.")
            result['error'] = "No working camera channels discovered. Check NVR status and RTSP/ONVIF availability."
            return result

        max_cams = getattr(settings, 'NVR_MAX_CAMERAS', 64)
        cameras = cameras[:max_cams]
        logger.info(f"Discovery complete. Found {len(cameras)} camera(s).")

        # Enhance camera list with raw_preview_url and rtsp_url for frontend
        from ..models import Camera
        from ..utils.url_parser import build_rtsp_url
        enhanced_cameras = []
        for cam in cameras:
            # We don't save to DB yet, just building the enhanced dict
            temp_cam = Camera(
                nvr=None, # Not yet saved
                name=cam.get('name', ''),
                camera_id=cam.get('camera_id', ''),
                preview_path=cam.get('preview_path', '/'),
                channel=cam.get('channel')
            )
            # Use a mock NVR for URL building
            from ..models import NVR
            mock_nvr = NVR(
                url=base_url,
                username=username,
                password=password,
                port=parsed.get('port'),
                brand=brand
            )
            temp_cam.nvr = mock_nvr
            
            enhanced_cam = cam.copy()
            enhanced_cam['preview_url'] = temp_cam.get_preview_url()
            enhanced_cam['raw_preview_url'] = temp_cam.get_raw_preview_url()
            
            # Construct RTSP URL if not provided by adapter
            if not enhanced_cam.get('rtsp_url'):
                enhanced_cam['rtsp_url'] = build_rtsp_url(
                    brand, parsed['hostname'], parsed.get('port'), 
                    username, password, enhanced_cam.get('channel', 1)
                )
            
            enhanced_cameras.append(enhanced_cam)

        result['cameras']      = enhanced_cameras
        result['camera_count'] = len(enhanced_cameras)
        result['success']      = True
        logger.info(f"Fetched {len(enhanced_cameras)} cameras from {base_url}")
    except Exception as e:
        result['error'] = f"Camera fetch error: {e}"
        logger.exception("Error fetching cameras")

    return result


def save_nvr_to_db(data: dict):
    """
    Persist an NVR and its cameras to the database.

    data keys: location, url, port, username, password, brand, cameras[]
    Returns: (nvr_instance, created_bool, saved_cameras_list)
    """
    from ..models import NVR, Camera

    parsed   = parse_nvr_url(data['url'], data.get('port'))
    base_url = parsed['base_url'] or data['url']

    nvr, created = NVR.objects.update_or_create(
        url=base_url,
        defaults={
            'location':      data.get('location', 'Unknown'),
            'port':          parsed.get('port'),
            'username':      data.get('username', ''),
            'password':      data.get('password', ''),
            'brand':         data.get('brand', 'unknown'),
            'is_connected':  True,
            'status':        'connected',
            'last_connected': timezone.now(),
            'error_message': '',
        }
    )

    saved = []
    for cam in data.get('cameras', []):
        camera_id = str(cam.get('camera_id', ''))
        if not camera_id:
            camera_id = str(cam.get('channel', len(saved) + 1))

        # Ensure unique camera_id within the NVR
        if not camera_id:
            camera_id = str(len(saved) + 1)

        camera, _ = Camera.objects.update_or_create(
            nvr=nvr,
            camera_id=camera_id,
            defaults={
                'name':         cam.get('name', f"Camera {camera_id}"),
                'preview_path': cam.get('preview_path', '/'),
                'rtsp_url':     cam.get('rtsp_url', ''),
                'camera_ip':    cam.get('camera_ip'),
                'channel':      cam.get('channel'),
                'is_active':    True,
            }
        )
        saved.append(camera)

    logger.info(f"Saved NVR '{nvr.location}' (id={nvr.id}, created={created}) with {len(saved)} cameras")
    return nvr, created, saved


def sync_nvr_cameras(nvr_id):
    """
    Reconnect to an existing NVR and refresh its camera list.
    - Adds new cameras
    - Updates existing ones
    - Removes old ones no longer present on NVR
    """
    from ..models import NVR, Camera
    try:
        nvr = NVR.objects.get(id=nvr_id)
        logger.info(f"Syncing cameras for NVR {nvr.location} ({nvr.url})")
        
        # 1. Connect and fetch
        result = connect_nvr(nvr.url, nvr.port, nvr.username, nvr.password)
        if not result['success']:
            return {'success': False, 'error': result['error']}
            
        # 2. Update NVR status
        nvr.brand = result['brand']
        nvr.mark_connected()
        
        # 3. Process cameras
        discovered_cameras = result['cameras']
        existing_cameras = {c.camera_id: c for c in nvr.cameras.all()}
        new_camera_ids = set()
        
        for cam_data in discovered_cameras:
            cid = cam_data['camera_id']
            new_camera_ids.add(cid)
            
            if cid in existing_cameras:
                # Update existing
                cam = existing_cameras[cid]
                cam.name = cam_data['name']
                cam.channel = cam_data['channel']
                cam.preview_path = cam_data['preview_path']
                cam.rtsp_url = cam_data['rtsp_url']
                cam.camera_ip = cam_data.get('camera_ip', cam.camera_ip)
                cam.is_active = True
                cam.save()
            else:
                # Create new
                Camera.objects.create(
                    nvr=nvr,
                    name=cam_data['name'],
                    camera_id=cid,
                    channel=cam_data['channel'],
                    preview_path=cam_data['preview_path'],
                    rtsp_url=cam_data['rtsp_url'],
                    camera_ip=cam_data.get('camera_ip'),
                    is_active=True
                )
        
        # 4. Deactivate/Remove cameras no longer present
        nvr.cameras.exclude(camera_id__in=new_camera_ids).delete()
        
        return {'success': True, 'camera_count': len(discovered_cameras)}
        
    except NVR.DoesNotExist:
        return {'success': False, 'error': "NVR not found"}
    except Exception as e:
        logger.error(f"Sync failed for NVR {nvr_id}: {e}")
        return {'success': False, 'error': str(e)}

def load_all_nvrs():
    """Return all NVRs prefetch-related cameras, ordered by creation date."""
    from ..models import NVR
    return NVR.objects.prefetch_related('cameras').all()


def get_nvr_json_list():
    """Return all NVRs and cameras as a serialisable list of dicts."""
    nvrs = load_all_nvrs()
    return [
        {
            'id':           nvr.id,
            'location':     nvr.location,
            'url':          nvr.url,
            'brand':        nvr.brand,
            'status':       nvr.status,
            'is_connected': nvr.is_connected,
            'cameras': [c.to_dict() for c in nvr.cameras.filter(is_active=True)],
        }
        for nvr in nvrs
    ]
