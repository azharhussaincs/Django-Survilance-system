"""
Views for the NVR Surveillance System.

URL map:
  GET/POST  /                     → login_view
  GET/POST  /login/               → login_view
  GET       /logout/              → logout_view
  GET       /dashboard/           → dashboard_view
  POST      /nvr/connect/         → api_connect_nvr      (AJAX)
  POST      /nvr/save/            → api_save_nvr         (AJAX)
  DELETE    /nvr/delete/<id>/     → api_delete_nvr       (AJAX)
  DELETE    /camera/delete/<id>/  → api_delete_camera    (AJAX)
  GET       /api/nvrs/            → api_list_nvrs        (AJAX)
  GET       /api/cameras/<nvr_id>/→ api_list_cameras     (AJAX)
"""

import json
import logging
import cv2
import time

from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from .models import NVR, Camera
from .services.nvr_service import connect_nvr, save_nvr_to_db, load_all_nvrs, get_nvr_json_list
from .utils.url_parser import validate_nvr_url

logger = logging.getLogger('core')

# ─────────────────────────────────────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────────────────────────────────────
ADMIN_USER = getattr(settings, 'APP_ADMIN_USERNAME', 'admin')
ADMIN_PASS = getattr(settings, 'APP_ADMIN_PASSWORD', 'admin123')


def _is_authenticated(request) -> bool:
    return bool(request.session.get('authenticated'))


def require_auth(view_fn):
    """Simple session-based auth decorator."""
    def wrapper(request, *args, **kwargs):
        if not _is_authenticated(request):
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Session expired. Please log in.'}, status=401)
            return redirect('login')
        return view_fn(request, *args, **kwargs)
    wrapper.__name__ = view_fn.__name__
    return wrapper


def _json_body(request) -> dict:
    """Parse JSON body, returning {} on failure."""
    try:
        return json.loads(request.body)
    except Exception:
        return {}


def _ok(**kwargs) -> JsonResponse:
    return JsonResponse({'success': True, **kwargs})


def _err(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({'success': False, 'error': msg}, status=status)


# ─────────────────────────────────────────────────────────────────────────────
# Auth views
# ─────────────────────────────────────────────────────────────────────────────
def login_view(request):
    """Login page (hardcoded credentials: admin / admin123)."""
    if _is_authenticated(request):
        return redirect('dashboard')

    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        if username == ADMIN_USER and password == ADMIN_PASS:
            request.session.cycle_key()
            request.session['authenticated'] = True
            request.session['username']      = username
            logger.info(f"Login success: {username}")
            return redirect('dashboard')
        else:
            logger.warning(f"Failed login: username='{username}'")
            error = 'Invalid username or password. Please try again.'

    return render(request, 'login.html', {'error': error})


def logout_view(request):
    """Flush session and redirect to login."""
    request.session.flush()
    return redirect('login')


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────
@require_auth
def dashboard_view(request):
    """Main dashboard: sidebar NVR tree + camera grid."""
    nvrs     = load_all_nvrs()
    username = request.session.get('username', 'Admin')
    return render(request, 'dashboard.html', {
        'nvrs':     nvrs,
        'username': username,
    })


# ─────────────────────────────────────────────────────────────────────────────
# NVR API – connect
# ─────────────────────────────────────────────────────────────────────────────
@require_auth
@require_http_methods(['POST'])
def api_connect_nvr(request):
    """
    AJAX: Test-connect to an NVR, detect brand, fetch cameras.
    Does NOT save to DB – call api_save_nvr() to persist.
    """
    data     = _json_body(request)
    url      = data.get('url', '').strip()
    port     = data.get('port', '').strip() or None
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not url:
        return _err('URL is required.')
    if not username:
        return _err('Username is required.')

    errors = validate_nvr_url(url)
    if errors:
        return _err(errors[0])

    result = connect_nvr(url, port, username, password)

    if not result['success']:
        return _err(result.get('error') or 'Connection failed.')

    return _ok(
        brand        = result['brand'],
        base_url     = result['base_url'],
        cameras      = result['cameras'],
        camera_count = result['camera_count'],
    )


# ─────────────────────────────────────────────────────────────────────────────
# NVR API – save
# ─────────────────────────────────────────────────────────────────────────────
@require_auth
@require_http_methods(['POST'])
def api_save_nvr(request):
    """AJAX: Save NVR + cameras to database."""
    data = _json_body(request)

    location = data.get('location', '').strip()
    url      = data.get('url', '').strip()
    if not location:
        return _err('Location is required.')
    if not url:
        return _err('URL is required.')

    try:
        nvr, created, saved_cameras = save_nvr_to_db(data)
    except Exception as e:
        logger.exception("Error saving NVR")
        return _err(str(e))

    return _ok(
        nvr_id       = nvr.id,
        nvr_location = nvr.location,
        brand        = nvr.brand,
        created      = created,
        cameras      = [c.to_dict() for c in saved_cameras],
    )


# ─────────────────────────────────────────────────────────────────────────────
# NVR API – delete
# ─────────────────────────────────────────────────────────────────────────────
@require_auth
@require_http_methods(['DELETE'])
def api_delete_nvr(request, nvr_id: int):
    """AJAX: Delete an NVR and all its cameras."""
    nvr = get_object_or_404(NVR, id=nvr_id)
    name = nvr.location
    nvr.delete()
    logger.info(f"Deleted NVR id={nvr_id} location='{name}'")
    return _ok(message=f"NVR '{name}' deleted.")


# ─────────────────────────────────────────────────────────────────────────────
# Camera API – delete
# ─────────────────────────────────────────────────────────────────────────────
@require_auth
@require_http_methods(['DELETE'])
def api_sync_nvr(request, nvr_id: int):
    """AJAX endpoint to refresh camera list from NVR."""
    if request.method != 'POST':
        return _err("Method not allowed", 405)
    
    from .services.nvr_service import sync_nvr_cameras
    result = sync_nvr_cameras(nvr_id)
    if result['success']:
        return _ok(camera_count=result['camera_count'])
    return _err(result['error'])


def api_delete_camera(request, camera_id: int):
    """AJAX: Delete a single camera."""
    cam  = get_object_or_404(Camera, id=camera_id)
    name = cam.name
    cam.delete()
    logger.info(f"Deleted camera id={camera_id} name='{name}'")
    return _ok(message=f"Camera '{name}' deleted.")


# ─────────────────────────────────────────────────────────────────────────────
# List APIs
# ─────────────────────────────────────────────────────────────────────────────
@require_auth
def api_list_nvrs(request):
    """AJAX: Return all NVRs with cameras as JSON."""
    return _ok(nvrs=get_nvr_json_list())


@require_auth
def api_list_cameras(request, nvr_id: int):
    """AJAX: Return cameras for a specific NVR."""
    nvr     = get_object_or_404(NVR, id=nvr_id)
    cameras = [c.to_dict() for c in nvr.cameras.filter(is_active=True)]
    return _ok(cameras=cameras, nvr_id=nvr_id, nvr_location=nvr.location)


# ─────────────────────────────────────────────────────────────────────────────
# Streaming
# ─────────────────────────────────────────────────────────────────────────────

def gen_frames(camera_id):
    """Video streaming generator function using OpenCV with FFMPEG."""
    from .models import Camera
    from django.shortcuts import get_object_or_404
    import time
    
    camera = get_object_or_404(Camera, id=camera_id)
    rtsp_url = camera.rtsp_url
    
    if not rtsp_url:
        logger.error(f"No RTSP URL for camera {camera_id}")
        return

    # Use OpenCV with FFMPEG backend
    # Optimization: Use TCP for RTSP (more stable on some NVRs)
    # REQUIREMENT: Reduce connection timeout to 3-5 seconds
    import os
    # stimeout is in microseconds. 5000000 = 5 seconds.
    # Added 'buffer_size' and 'max_delay' for smoother MJPEG
    # Added 'rtsp_transport;tcp' specifically for Hikvision/Dahua
    # IMPORTANT: Use '|' separator for multiple options and ensure no spaces around them.
    # We also set stimeout for FFMPEG specifically.
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000|buffer_size;1024000|max_delay;500000"
    
    # NEW: Try to set timeout via individual flags if the global string fails
    # Also attempt to strip extra params that might cause Dahua to timeout
    clean_rtsp_url = rtsp_url
    if "cam/realmonitor" in rtsp_url and "unicast=true" in rtsp_url:
        # Some Dahua firmware hangs on extra ONVIF parameters in RTSP
        import re
        clean_rtsp_url = re.sub(r'&unicast=true&proto=Onvif', '', rtsp_url, flags=re.I)
        logger.debug(f"Cleaned Dahua URL for better compatibility: {clean_rtsp_url}")
    
    # Special fix for the port-based simple RTSP format: rtsp://user:pass@ip:port?channel=N
    # Users reported this format working on VLC.
    if "?" in rtsp_url and "channel=" in rtsp_url and "/" not in rtsp_url.split("://")[-1].split("?")[0]:
        # This is already a clean format, don't mess with it in the primary attempt
        pass

    logger.debug(f"Opening RTSP stream for camera {camera_id}: {clean_rtsp_url} with transport=tcp and timeout=5s")
    cap = cv2.VideoCapture(clean_rtsp_url, cv2.CAP_FFMPEG)
    
    # Check if we should try a fallback URL if the primary fails
    if not cap.isOpened():
        logger.warning(f"Primary RTSP failed for camera {camera_id}. Attempting fallback...")
        # Fallback 1: Try common Hikvision/Dahua paths if ONVIF path failed
        fallback_url = None
        
        # If the URL is an ONVIF-style one that failed, try the standard ISAPI path
        import re
        # MediaProfile_Channel1_SubStream1 -> channel 1
        # /cam/realmonitor?channel=3&subtype=1&unicast=true&proto=Onvif -> channel 3
        match = re.search(r'Channel(\d+)', rtsp_url, re.IGNORECASE)
        if not match:
            # Try channel=N pattern for Dahua
            match = re.search(r'channel=(\d+)', rtsp_url, re.IGNORECASE)
            
        if match:
            channel_num = match.group(1)
            # Use the NVR's hostname and credentials from the original URL
            # rtsp://user:pass@ip:port/path
            url_match = re.match(r'(rtsp://[^/?]+)', rtsp_url)
            if url_match:
                base_auth_host = url_match.group(1)
                
                # 1. Try the "Simple Port-Based" format (VLC style)
                # This uses the NVR's actual web port (like 82) if provided
                nvr_web_port = camera.nvr.port or 80
                from urllib.parse import urlparse
                p = urlparse(camera.nvr.get_base_url())
                nvr_host = p.hostname or ''
                nvr_port = p.port or nvr_web_port
                
                from .utils.url_parser import encode_password
                user_pass = f"{camera.nvr.username}:{encode_password(camera.nvr.password)}"
                
                # Format: rtsp://user:pass@ip:82?channel=2
                fallback_url = f"rtsp://{user_pass}@{nvr_host}:{nvr_port}?channel={channel_num}"
                logger.info(f"Attempting simple port-based fallback for channel {channel_num}: {fallback_url}")
                cap = cv2.VideoCapture(fallback_url, cv2.CAP_FFMPEG)
                if cap.isOpened():
                    logger.info(f"Simple port-based fallback SUCCESS for camera {camera_id}")
                    rtsp_url = fallback_url
                
                if not cap.isOpened():
                    # Format: rtsp://user:pass@ip:554/cam/realmonitor?channel=1&subtype=1
                    # Ensure we have a trailing slash for base_auth_host if needed
                    base_rtsp = base_auth_host + "/" if not base_auth_host.endswith("/") else base_auth_host
                    
                    # Try "clean" Dahua path (no extra params like unicast/proto):
                    fallback_url = f"{base_rtsp}cam/realmonitor?channel={channel_num}&subtype=1"
                    logger.info(f"Attempting clean Dahua fallback for channel {channel_num}: {fallback_url}")
                    cap = cv2.VideoCapture(fallback_url, cv2.CAP_FFMPEG)
                    if cap.isOpened():
                        logger.info(f"Dahua fallback SUCCESS for camera {camera_id}")
                        rtsp_url = fallback_url
                    else:
                        # Try Hikvision path: /Streaming/Channels/101
                        fallback_url = f"{base_rtsp}Streaming/Channels/{channel_num}01"
                        logger.info(f"Attempting Hikvision fallback for channel {channel_num}: {fallback_url}")
                        cap = cv2.VideoCapture(fallback_url, cv2.CAP_FFMPEG)
                        if cap.isOpened():
                            logger.info(f"Hikvision fallback SUCCESS for camera {camera_id}")
                            rtsp_url = fallback_url
                        else:
                            # Try Dahua subtype=0 (main stream)
                            fallback_url = f"{base_rtsp}cam/realmonitor?channel={channel_num}&subtype=0"
                            logger.info(f"Attempting Dahua mainstream fallback for channel {channel_num}: {fallback_url}")
                            cap = cv2.VideoCapture(fallback_url, cv2.CAP_FFMPEG)
                            if cap.isOpened():
                                logger.info(f"Dahua mainstream fallback SUCCESS for camera {camera_id}")
                                rtsp_url = fallback_url
                            else:
                                fallback_url = None # Reset if all guesses failed
        
        if not cap.isOpened():
            # General fallback swapping MainStream <-> SubStream
            if "SubStream" in rtsp_url:
                fallback_url = rtsp_url.replace("SubStream", "MainStream")
            elif "/Streaming/Channels/" in rtsp_url and "02" in rtsp_url:
                 fallback_url = rtsp_url.replace("02", "01")
            elif "subtype=1" in rtsp_url:
                 fallback_url = rtsp_url.replace("subtype=1", "subtype=0")
            elif "subtype=0" in rtsp_url:
                 fallback_url = rtsp_url.replace("subtype=0", "subtype=1")
            
            if fallback_url and fallback_url != rtsp_url:
                logger.info(f"Trying general stream fallback: {fallback_url}")
                cap = cv2.VideoCapture(fallback_url, cv2.CAP_FFMPEG)
                if cap.isOpened():
                    logger.info(f"General fallback SUCCESS for camera {camera_id}")
                    rtsp_url = fallback_url
    
    if not cap.isOpened():
        # FINAL ATTEMPT: Try without TCP (UDP)
        logger.warning(f"TCP failed for camera {camera_id}. Attempting UDP...")
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;udp|stimeout;5000000"
        cap = cv2.VideoCapture(clean_rtsp_url, cv2.CAP_FFMPEG)
        
    if not cap.isOpened() and rtsp_url != clean_rtsp_url:
        # If the cleaned URL failed, try the original one as a last resort
        logger.warning(f"Cleaned URL failed, trying original for camera {camera_id}...")
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        
    if not cap.isOpened():
        logger.error(f"Could not open RTSP stream for camera {camera_id}: {rtsp_url}")
        # Return a "Stream Offline" placeholder image
        yield _get_offline_frame("Stream Offline")
        return
    
    logger.info(f"RTSP stream successfully opened for camera {camera_id}")

    try:
        last_frame_time = time.time()
        stall_threshold = 15 # seconds
        
        while True:
            # Check for stalls
            if time.time() - last_frame_time > stall_threshold:
                logger.warning(f"RTSP stream stall detected for camera {camera_id}, reconnecting...")
                cap.release()
                time.sleep(1)
                cap = cv2.VideoCapture(clean_rtsp_url, cv2.CAP_FFMPEG)
                last_frame_time = time.time()
                if not cap.isOpened():
                    yield _get_offline_frame("Reconnecting...")
                    time.sleep(2)
                    continue

            success, frame = cap.read()
            if not success:
                # Reconnect on failure
                cap.release()
                time.sleep(2)
                cap = cv2.VideoCapture(clean_rtsp_url, cv2.CAP_FFMPEG)
                if not cap.isOpened():
                    yield _get_offline_frame("Connection Lost")
                    break
                continue
            
            last_frame_time = time.time()
            
            # Optimization: Downscale if frame is massive (4K etc) for smoother MJPEG
            h, w = frame.shape[:2]
            if w > 1280:
                new_w = 1280
                new_h = int(h * (1280 / w))
                frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

            # Encode to JPEG
            ret, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if not ret:
                continue
                
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            
            # Small sleep to yield control
            time.sleep(0.03) # Limit to ~30 FPS max
            
    except GeneratorExit:
        logger.debug(f"Streaming generator for camera {camera_id} stopped.")
    except Exception as e:
        logger.exception(f"Error in streaming generator for camera {camera_id}")
    finally:
        if cap:
            cap.release()

def _get_offline_frame(text="Offline"):
    """Generate a placeholder JPEG frame with text."""
    import numpy as np
    img = np.zeros((480, 640, 3), np.uint8)
    cv2.putText(img, text, (150, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 2)
    ret, buffer = cv2.imencode('.jpg', img)
    frame_bytes = buffer.tobytes()
    return (b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@require_auth
def camera_stream_view(request, camera_id):
    """Endpoint that serves the MJPEG stream for a camera."""
    return StreamingHttpResponse(gen_frames(camera_id),
                                 content_type='multipart/x-mixed-replace; boundary=frame')
