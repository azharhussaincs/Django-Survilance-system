"""
ONVIF discovery and management utilities.
"""
import logging
from onvif import ONVIFCamera
from zeep.exceptions import Fault
import cv2
import socket
from .url_parser import build_rtsp_url, encode_password

logger = logging.getLogger('core')

def discover_onvif_cameras(host, port, username, password):
    """
    Connect to NVR via ONVIF and discover camera channels.
    Returns a list of dicts: {name, camera_id, rtsp_url, channel}
    """
    cameras = []
    try:
        from .helpers import CONNECT_TIMEOUT
        
        # Common ONVIF ports: 80, 8080, 8888, 8000, 5000, 82
        onvif_ports = [port] if port not in [80, 8080] else [port, 80, 8080, 8888, 8000]
        if 82 not in onvif_ports: onvif_ports.append(82)
        
        mycam = None
        working_port = None
        
        # Fast TCP pre-check to avoid long timeouts in ONVIFCamera
        from .helpers import check_port
        
        for p in onvif_ports:
            try:
                logger.debug(f"Trying ONVIF connection to {host}:{p}")
                if not check_port(host, p, timeout=2):
                    continue
                
                # We need to provide the wsdl path if not in default location, 
                # but onvif-zeep usually finds it if installed via pip.
                mycam = ONVIFCamera(host, p, username, password)
                # Test connection by getting device info
                info = mycam.devicemgmt.GetDeviceInformation()
                working_port = p
                logger.info(f"ONVIF connected successfully to {host}:{working_port}")
                break
            except Exception as e:
                logger.debug(f"ONVIF connection failed on port {p}: {e}")
                continue
        
        if not mycam or not working_port:
            logger.warning(f"Could not establish ONVIF connection to {host}")
            return []

        # Get Media Service
        media_service = mycam.create_media_service()
        # Get Profiles
        profiles = media_service.GetProfiles()
        logger.info(f"ONVIF Response: Found {len(profiles)} profiles")
        
        # Also try Media2 service (ONVIF Profile T) which often has more detailed lists in newer NVRs
        media2_service = None
        try:
            media2_service = mycam.create_media2_service()
            m2_profiles = media2_service.GetProfiles()
            if m2_profiles and (len(m2_profiles) > len(profiles) or not profiles):
                logger.info(f"ONVIF Media2: Found {len(m2_profiles)} profiles. Preferring Media2.")
                profiles = m2_profiles
                media_service = media2_service # We'll try to use this as primary
        except:
            pass

        # If we still have only 1 profile or 0 profiles, try to get VideoSources
        # Some NVRs have many video sources but don't automatically create profiles for all of them.
        if len(profiles) <= 1:
            try:
                sources = media_service.GetVideoSources()
                if len(sources) > len(profiles):
                    logger.info(f"ONVIF: Found {len(sources)} VideoSources but only {len(profiles)} profiles. Attempting to fetch streams for each source.")
                    # We might not be able to fetch URIs without profiles, 
                    # but we can at least log this discrepancy.
            except:
                pass
        
        # Dedup by name and URI to avoid duplicates from multiple services
        seen_uris = set()

        for i, profile in enumerate(profiles):
            token = profile.token
            name = profile.Name or f"Camera {i+1}"
            
            # Get Stream URI
            try:
                # Standard Media 1 call
                uri_obj = None
                try:
                    stream_setup = {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}}
                    uri_obj = media_service.GetStreamUri({'StreamSetup': stream_setup, 'ProfileToken': token})
                except:
                    # Try simplified call
                    try:
                        uri_obj = media_service.GetStreamUri(token, 'RTP-Unicast', 'RTSP')
                    except:
                        pass
                
                if not uri_obj or not hasattr(uri_obj, 'Uri'):
                    continue
                    
                raw_rtsp_url = uri_obj.Uri
                if raw_rtsp_url in seen_uris:
                    continue
                seen_uris.add(raw_rtsp_url)

                # Inject credentials if missing in the URI
                rtsp_url = inject_creds_into_rtsp(raw_rtsp_url, username, password)
                
                cameras.append({
                    'name': name,
                    'camera_id': token,
                    'rtsp_url': rtsp_url,
                    'channel': i + 1,
                    'camera_ip': host
                })
                logger.info(f"Discovered ONVIF camera: {name} (Token: {token}) -> {rtsp_url}")
            except Exception as e:
                logger.debug(f"Failed to get stream URI for profile {token}: {e}")

    except Exception as e:
        logger.error(f"ONVIF discovery error for {host}: {e}")
    
    return cameras

def inject_creds_into_rtsp(url, username, password):
    """Ensure username:password is in the RTSP URL."""
    if not url: return ""
    if "@" in url: return url # Already has creds?
    
    prefix = "rtsp://"
    if url.startswith(prefix):
        content = url[len(prefix):]
        return f"{prefix}{username}:{encode_password(password)}@{content}"
    return url

def validate_rtsp_stream(rtsp_url, timeout_ms=8000):
    """
    Test if an RTSP stream can be opened and decoded.
    Returns (True, "") or (False, "error message")
    """
    if not rtsp_url:
        return False, "Empty RTSP URL"
    
    # Set transport to TCP for validation as well
    import os
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
    
    try:
        logger.debug(f"Validating RTSP stream: {rtsp_url}")
        # Use FFMPEG backend
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            return False, "Could not open RTSP stream"
        
        # Try to read one frame
        # Set a very short timeout for validation (3 seconds)
        try:
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout_ms)
            # Some versions of OpenCV/FFmpeg don't support CAP_PROP_OPEN_TIMEOUT_MSEC
            # So we also set it via environment variable (handled above)
        except:
            pass
    
        ret, frame = cap.read()
        cap.release()
        
        if ret and frame is not None:
            logger.info(f"RTSP stream validation SUCCESS for {rtsp_url}")
            return True, ""
        else:
            logger.warning(f"RTSP stream validation FAILED for {rtsp_url}: Opened but no frame")
            return False, "Stream opened but failed to decode frame"
            
    except Exception as e:
        logger.error(f"RTSP stream validation ERROR for {rtsp_url}: {e}")
        return False, str(e)

def probe_rtsp_channels(host, port, username, password, brand, max_channels=16):
    """
    Manually probe RTSP channels if ONVIF and APIs fail.
    REQUIREMENT: Scan up to 16 channels by default (fast discovery).
    Skip slow RTSP validation during discovery.
    """
    working_cameras = []
    rtsp_port = 554 # Standard
    
    # Check if RTSP port is even open (fast TCP check)
    from .helpers import check_port
    if not check_port(host, rtsp_port):
        logger.warning(f"RTSP port {rtsp_port} is closed on {host}. Skipping probe.")
        return []

    logger.info(f"Starting fast RTSP channel generation for {host} (max {max_channels} channels)")

    for ch in range(1, max_channels + 1):
        url = build_rtsp_url(brand, host, rtsp_port, username, password, ch)
        # REQUIREMENT: Do not validate each channel with OpenCV for speed.
        # Just generate the entries and let the player handle connection later.
        working_cameras.append({
            'name': f"Camera {ch}",
            'camera_id': str(ch),
            'rtsp_url': url,
            'channel': ch,
            'camera_ip': host
        })
                
    logger.info(f"Fast RTSP channel discovery complete for {host}. Generated {len(working_cameras)} channels.")
    return working_cameras
