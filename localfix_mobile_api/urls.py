import mimetypes
import os
import re

import django
from django.conf import settings
from django.contrib import admin
from django.db.models import Sum
from django.http import FileResponse, Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.urls import path, include, re_path
from django.utils import timezone

from mobile_api.models import (
    CallSession,
    ChatMessage,
    ContentModerationLog,
    FeedPost,
    LocationLog,
    Notification,
    PostComment,
    ReelComment,
    StoredMedia,
    TeamMember,
    UserProfile,
    UserStory,
    VideoReel,
)


def serve_db_media_range(request, uuid_key, filename):
    """Serve DB-persisted photos, avatars & videos with HTTP Range (206 Partial Content) support."""
    media = StoredMedia.objects.filter(uuid_key=uuid_key).first()
    if not media:
        raise Http404('Media not found.')

    raw = bytes(media.data)
    file_size = len(raw)
    content_type = media.content_type or mimetypes.guess_type(filename)[0] or 'application/octet-stream'

    range_header = request.META.get('HTTP_RANGE', '').strip()
    range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
    if range_match:
        first_byte = int(range_match.group(1))
        last_byte = int(range_match.group(2)) if range_match.group(2) else file_size - 1
        last_byte = min(last_byte, file_size - 1)
        if first_byte >= file_size:
            resp = HttpResponse(status=416)
            resp['Content-Range'] = f'bytes */{file_size}'
            return resp
        chunk = raw[first_byte : last_byte + 1]
        resp = HttpResponse(chunk, status=206, content_type=content_type)
        resp['Content-Length'] = str(len(chunk))
        resp['Content-Range'] = f'bytes {first_byte}-{last_byte}/{file_size}'
        resp['Accept-Ranges'] = 'bytes'
        resp['Cache-Control'] = 'public, max-age=86400'
        return resp

    resp = HttpResponse(raw, content_type=content_type)
    resp['Content-Length'] = str(file_size)
    resp['Accept-Ranges'] = 'bytes'
    resp['Cache-Control'] = 'public, max-age=86400'
    return resp


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


def api_root(request):
    accept = request.META.get('HTTP_ACCEPT', '')
    wants_json = (
        request.GET.get('format') == 'json'
        or ('application/json' in accept and 'text/html' not in accept)
    )
    if wants_json:
        return JsonResponse({
            'service': 'LocalFix Mobile Django Backend',
            'status': 'running',
            'endpoints': {
                'health': '/api/health/',
                'ip_location': '/api/location/ip/',
                'gps_update': '/api/location/update/',
                'gps_history': '/api/location/history/',
                'login': '/api/auth/login/',
                'register': '/api/auth/register/',
                'google_auth': '/api/auth/google/',
                'users': '/api/users/',
                'profile': '/api/profile/',
                'subscription_checkout': '/api/subscription/checkout/',
                'subscription_verify': '/api/subscription/verify/',
                'localfix_ai': '/api/ai/ask/',
                'media_upload': '/api/media/upload/',
                'feed': '/api/feed/',
                'reels': '/api/reels/',
                'stories': '/api/stories/',
                'follow': '/api/follow/toggle/',
                'team': '/api/team/',
                'notifications': '/api/notifications/',
                'chat_conversations': '/api/chat/conversations/',
                'chat_messages': '/api/chat/messages/',
                'chat_unread': '/api/chat/unread/',
                'calls_start': '/api/calls/start/',
                'nearby_artisans': '/api/artisans/nearby/',
                'escrow': '/api/escrow/',
                'admin': '/admin/',
            },
        })

    now = timezone.now()
    stats = {
        'users_total': 0,
        'artisans_total': 0,
        'clients_total': 0,
        'verified_total': 0,
        'company_verified': 0,
        'paid_verified': 0,
        'posts_total': 0,
        'reels_total': 0,
        'comments_total': 0,
        'active_stories': 0,
        'stories_total': 0,
        'messages_total': 0,
        'messages_unread': 0,
        'calls_total': 0,
        'gps_logs_total': 0,
        'team_links_total': 0,
        'moderation_total': 0,
        'locked_users': 0,
        'media_count': 0,
        'media_mb': '0.0',
        'notifications_total': 0,
    }
    recent_users = []
    recent_moderation = []

    try:
        stats['users_total'] = UserProfile.objects.count()
        stats['artisans_total'] = UserProfile.objects.filter(role__iexact='Artisan').count()
        stats['clients_total'] = max(0, stats['users_total'] - stats['artisans_total'])
        stats['company_verified'] = UserProfile.objects.filter(is_company_verified=True).count()
        stats['paid_verified'] = UserProfile.objects.filter(is_company_verified=False, verified_until__gt=now).count()
        stats['verified_total'] = stats['company_verified'] + stats['paid_verified']
        stats['locked_users'] = UserProfile.objects.filter(locked_until__gt=now).count()
        stats['posts_total'] = FeedPost.objects.count()
        stats['reels_total'] = VideoReel.objects.count()
        stats['comments_total'] = PostComment.objects.count() + ReelComment.objects.count()
        stats['stories_total'] = UserStory.objects.count()
        stats['active_stories'] = UserStory.objects.filter(expires_at__gt=now).count()
        stats['messages_total'] = ChatMessage.objects.count()
        stats['messages_unread'] = ChatMessage.objects.filter(is_read=False).count()
        stats['calls_total'] = CallSession.objects.count()
        stats['gps_logs_total'] = LocationLog.objects.count()
        stats['team_links_total'] = TeamMember.objects.count()
        stats['moderation_total'] = ContentModerationLog.objects.count()
        stats['notifications_total'] = Notification.objects.count()
        stats['media_count'] = StoredMedia.objects.count()
        media_bytes = StoredMedia.objects.aggregate(total=Sum('size')).get('total') or 0
        stats['media_mb'] = f'{media_bytes / (1024 * 1024):.2f}'
        recent_users = list(UserProfile.objects.order_by('-id')[:6])
        recent_moderation = list(ContentModerationLog.objects.order_by('-created_at')[:6])
    except Exception:
        pass

    db_engine = settings.DATABASES['default'].get('ENGINE', '')
    db_engine_label = 'Neon PostgreSQL' if 'postgresql' in db_engine else 'SQLite Local'

    paystack_ok = bool(os.environ.get('PAYSTACK_SECRET_KEY', '').strip())
    stripe_ok = bool(os.environ.get('STRIPE_SECRET_KEY', '').strip())
    if paystack_ok and stripe_ok:
        payment_gateway_ready = True
        payment_gateway_label = 'Paystack + Stripe Active'
    elif paystack_ok:
        payment_gateway_ready = True
        payment_gateway_label = 'Paystack Live'
    elif stripe_ok:
        payment_gateway_ready = True
        payment_gateway_label = 'Stripe Live'
    else:
        payment_gateway_ready = False
        payment_gateway_label = 'Keys Pending'

    ai_gemini_ready = bool(os.environ.get('GEMINI_API_KEY', '').strip())

    api_endpoints = [
        {'method': 'GET', 'path': '/api/health/', 'label': 'System health & database ping'},
        {'method': 'POST', 'path': '/api/auth/register/', 'label': 'User registration (Client / Artisan)'},
        {'method': 'POST', 'path': '/api/auth/login/', 'label': 'Email & password sign-in'},
        {'method': 'POST', 'path': '/api/auth/google/', 'label': 'Google OAuth sign-in & role sync'},
        {'method': 'GET/PATCH', 'path': '/api/profile/', 'label': 'Profile, avatar, dark mode & badge status'},
        {'method': 'GET', 'path': '/api/users/', 'label': 'Global member directory & GPS coordinates'},
        {'method': 'POST', 'path': '/api/location/update/', 'label': 'Auto-GPS exact address capture'},
        {'method': 'GET', 'path': '/api/location/history/', 'label': 'Employer employee GPS trail'},
        {'method': 'GET/POST', 'path': '/api/feed/', 'label': 'Fixes-Only photo/video feed posts'},
        {'method': 'GET/POST', 'path': '/api/reels/', 'label': 'Artisan fix video reels'},
        {'method': 'GET/POST', 'path': '/api/stories/', 'label': '24-hour stories & viewer tracking'},
        {'method': 'POST', 'path': '/api/media/upload/', 'label': 'DB-persisted image/video/voice upload'},
        {'method': 'GET/POST', 'path': '/api/chat/messages/', 'label': 'Real-time chat, images & voice notes'},
        {'method': 'GET', 'path': '/api/chat/unread/', 'label': 'Strict unread message badge counter'},
        {'method': 'POST', 'path': '/api/calls/start/', 'label': '2-way WebRTC audio/video signaling'},
        {'method': 'POST', 'path': '/api/subscription/checkout/', 'label': 'Real Paystack / Stripe badge checkout'},
        {'method': 'POST', 'path': '/api/ai/ask/', 'label': 'LocalFix AI client & artisan assistant'},
        {'method': 'GET/POST', 'path': '/api/notifications/', 'label': 'Real persistent user notifications'},
    ]

    context = {
        'stats': stats,
        'recent_users': recent_users,
        'recent_moderation': recent_moderation,
        'db_engine_label': db_engine_label,
        'payment_gateway_ready': payment_gateway_ready,
        'payment_gateway_label': payment_gateway_label,
        'ai_gemini_ready': ai_gemini_ready,
        'django_version': django.get_version(),
        'api_endpoints': api_endpoints,
    }
    return render(request, 'portal.html', context)


urlpatterns = [
    path('', api_root, name='api-root'),
    path('admin/', admin.site.urls),
    path('api/', include('mobile_api.urls')),
    re_path(r'^media/db/(?P<uuid_key>[^/]+)/(?P<filename>.+)$', serve_db_media_range),
    re_path(r'^media/(?P<path>.*)$', serve_media_range),
]
