import mimetypes
import os
import re

from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, Http404, JsonResponse, StreamingHttpResponse
from django.urls import path, include, re_path


def _file_iterator(file_path, offset=0, length=None, chunk_size=8192):
    with open(file_path, 'rb') as f:
        f.seek(offset)
        remaining = length
        while True:
            to_read = chunk_size if remaining is None else min(chunk_size, remaining)
            if to_read <= 0:
                break
            data = f.read(to_read)
            if not data:
                break
            if remaining is not None:
                remaining -= len(data)
            yield data


def serve_media_range(request, path):
    """Serve uploaded photos & videos with HTTP Range (206 Partial Content) support for Android ExoPlayer."""
    media_root = os.path.abspath(settings.MEDIA_ROOT)
    full_path = os.path.abspath(os.path.join(media_root, path.lstrip('/')))
    if not full_path.startswith(media_root) or not os.path.isfile(full_path):
        raise Http404('Media file not found.')

    file_size = os.path.getsize(full_path)
    content_type, _ = mimetypes.guess_type(full_path)
    if not content_type:
        ext = os.path.splitext(full_path)[1].lower()
        content_type = {
            '.mp4': 'video/mp4',
            '.mov': 'video/quicktime',
            '.webm': 'video/webm',
            '.3gp': 'video/3gpp',
            '.mkv': 'video/x-matroska',
        }.get(ext, 'application/octet-stream')

    range_header = request.META.get('HTTP_RANGE', '').strip()
    range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
    if range_match:
        first_byte = int(range_match.group(1))
        last_byte = int(range_match.group(2)) if range_match.group(2) else file_size - 1
        last_byte = min(last_byte, file_size - 1)
        if first_byte >= file_size:
            resp = StreamingHttpResponse(status=416)
            resp['Content-Range'] = f'bytes */{file_size}'
            return resp
        length = last_byte - first_byte + 1
        resp = StreamingHttpResponse(
            _file_iterator(full_path, offset=first_byte, length=length),
            status=206,
            content_type=content_type,
        )
        resp['Content-Length'] = str(length)
        resp['Content-Range'] = f'bytes {first_byte}-{last_byte}/{file_size}'
        resp['Accept-Ranges'] = 'bytes'
        return resp

    resp = FileResponse(open(full_path, 'rb'), content_type=content_type)
    resp['Content-Length'] = str(file_size)
    resp['Accept-Ranges'] = 'bytes'
    return resp


def api_root(_request):
    return JsonResponse({
        'service': 'LocalFix Mobile Django Backend',
        'status': 'running',
        'endpoints': {
            'health': '/api/health/',
            'ip_location': '/api/location/ip/',
            'login': '/api/auth/login/',
            'register': '/api/auth/register/',
            'google_auth': '/api/auth/google/',
            'users': '/api/users/',
            'profile': '/api/profile/',
            'media_upload': '/api/media/upload/',
            'feed': '/api/feed/',
            'reels': '/api/reels/',
            'chat_conversations': '/api/chat/conversations/',
            'chat_messages': '/api/chat/messages/',
            'nearby_artisans': '/api/artisans/nearby/',
            'escrow': '/api/escrow/',
            'admin': '/admin/',
        },
    })


urlpatterns = [
    path('', api_root, name='api-root'),
    path('admin/', admin.site.urls),
    path('api/', include('mobile_api.urls')),
    re_path(r'^media/(?P<path>.*)$', serve_media_range),
]
