from datetime import timedelta
import json
import mimetypes
import os
import secrets
import urllib.request
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.core.files.storage import FileSystemStorage
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response

from .models import (
    UserProfile,
    LocationLog,
    StoredMedia,
    FeedPost,
    PostLike,
    PostComment,
    VideoReel,
    ReelLike,
    ReelComment,
    ChatMessage,
    EscrowContract,
    CallSession,
    UserStory,
    UserFollow,
    TeamMember,
)
from .serializers import (
    UserProfileSerializer,
    FeedPostSerializer,
    PostCommentSerializer,
    VideoReelSerializer,
    ReelCommentSerializer,
    ChatMessageSerializer,
    EscrowContractSerializer,
)

GOOGLE_CLIENT_ID = os.environ.get(
    'GOOGLE_CLIENT_ID',
    '589519175794-4ue3d2mdr4i2hk84qkljkdosf4ftbdf3.apps.googleusercontent.com',
)


def _extract_client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def _lookup_ip_location(ip_address):
    endpoints = []
    if ip_address and not ip_address.startswith(('127.', '10.', '192.168.', '::1')):
        endpoints.append(f'https://ipwho.is/{ip_address}')
        endpoints.append(f'https://ipapi.co/{ip_address}/json/')
    else:
        endpoints.append('https://ipwho.is/')
        endpoints.append('https://ipapi.co/json/')

    for url in endpoints:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'LocalFix-Mobile/1.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if 'ipwho.is' in url and data.get('success', False):
                    currency = data.get('currency') or {}
                    return {
                        'ip': data.get('ip', ip_address),
                        'city': data.get('city', ''),
                        'region': data.get('region', ''),
                        'country': data.get('country', ''),
                        'country_code': data.get('country_code', 'US'),
                        'currency_code': currency.get('code', 'USD'),
                        'latitude': data.get('latitude'),
                        'longitude': data.get('longitude'),
                    }
                if 'ipapi.co' in url and not data.get('error'):
                    return {
                        'ip': data.get('ip', ip_address),
                        'city': data.get('city', ''),
                        'region': data.get('region', ''),
                        'country': data.get('country_name', ''),
                        'country_code': data.get('country_code', 'US'),
                        'currency_code': data.get('currency', 'USD'),
                        'latitude': data.get('latitude'),
                        'longitude': data.get('longitude'),
                    }
        except Exception:
            continue
    return None


@api_view(['GET'])
def health_check(request):
    return Response({
        'status': 'ok',
        'framework': 'Django REST Framework',
        'service': 'localfix-app-backend',
        'timestamp': timezone.now().isoformat(),
    })


@api_view(['GET'])
def location_from_ip(request):
    ip_address = _extract_client_ip(request)
    loc = _lookup_ip_location(ip_address)
    if not loc:
        return Response(
            {'success': False, 'error': 'Unable to resolve IP location right now.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response({'success': True, 'location': loc})


@api_view(['POST'])
def auth_register(request):
    name = (request.data.get('name') or '').strip()
    email = (request.data.get('email') or '').strip().lower()
    password = request.data.get('password') or ''
    role = (request.data.get('role') or 'Customer').strip()
    city = (request.data.get('city') or '').strip()
    country_code = (request.data.get('country_code') or 'US').strip().upper()

    if not name:
        return Response({'success': False, 'error': 'Full name is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if not email or '@' not in email:
        return Response({'success': False, 'error': 'Please enter a valid email address.'}, status=status.HTTP_400_BAD_REQUEST)
    if len(password) < 6:
        return Response({'success': False, 'error': 'Password must be at least 6 characters.'}, status=status.HTTP_400_BAD_REQUEST)
    if UserProfile.objects.filter(email=email).exists():
        return Response(
            {'success': False, 'error': 'An account with this email already exists. Please log in.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    handle = '@' + email.split('@')[0].replace('.', '_')
    profile = UserProfile.objects.create(
        name=name,
        handle=handle,
        email=email,
        password_hash=make_password(password),
        auth_provider='email',
        role=role if role in ('Customer', 'Artisan') else 'Customer',
        city=city,
        country_code=country_code,
    )
    token = f'lf_{secrets.token_urlsafe(32)}'
    return Response(
        {'success': True, 'token': token, 'user': UserProfileSerializer(profile).data},
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
def auth_login(request):
    email = (request.data.get('email') or '').strip().lower()
    password = request.data.get('password') or ''

    if not email or not password:
        return Response(
            {'success': False, 'error': 'Email and password are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    profile = UserProfile.objects.filter(email=email).first()
    if not profile:
        return Response(
            {'success': False, 'error': 'No account found with this email. Please create an account first.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if profile.auth_provider == 'google' and not profile.password_hash:
        return Response(
            {'success': False, 'error': 'This account uses Google Sign-In. Please tap Continue with Google.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if not check_password(password, profile.password_hash):
        return Response(
            {'success': False, 'error': 'Incorrect password. Please try again.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    token = f'lf_{secrets.token_urlsafe(32)}'
    return Response({'success': True, 'token': token, 'user': UserProfileSerializer(profile).data})


@api_view(['POST'])
def auth_google(request):
    id_token = (request.data.get('id_token') or '').strip()
    role = (request.data.get('role') or 'Customer').strip()
    city = (request.data.get('city') or '').strip()
    country_code = (request.data.get('country_code') or 'US').strip().upper()

    if not id_token:
        return Response({'success': False, 'error': 'Missing Google id_token.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        verify_url = f'https://oauth2.googleapis.com/tokeninfo?id_token={id_token}'
        with urllib.request.urlopen(verify_url, timeout=8) as resp:
            info = json.loads(resp.read().decode('utf-8'))
    except Exception:
        return Response({'success': False, 'error': 'Invalid or expired Google token.'}, status=status.HTTP_401_UNAUTHORIZED)

    aud = info.get('aud', '')
    if aud != GOOGLE_CLIENT_ID:
        return Response(
            {'success': False, 'error': 'Google token audience does not match LocalFix Client ID.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    email = (info.get('email') or '').strip().lower()
    if not email:
        return Response({'success': False, 'error': 'Google account has no email.'}, status=status.HTTP_400_BAD_REQUEST)

    name = info.get('name') or email.split('@')[0]
    google_sub = info.get('sub') or ''
    picture = info.get('picture') or ''
    handle = '@' + email.split('@')[0].replace('.', '_')

    profile, created = UserProfile.objects.get_or_create(
        email=email,
        defaults={
            'name': name,
            'handle': handle,
            'google_id': google_sub,
            'auth_provider': 'google',
            'avatar_url': picture,
            'role': role if role in ('Customer', 'Artisan') else 'Customer',
            'city': city,
            'country_code': country_code,
            'is_company_verified': email.endswith('@localfix.com'),
        },
    )
    if not created:
        changed = []
        if role in ('Customer', 'Artisan') and profile.role != role:
            profile.role = role
            changed.append('role')
        if not profile.google_id and google_sub:
            profile.google_id = google_sub
            changed.append('google_id')
        if not profile.avatar_url and picture:
            profile.avatar_url = picture
            changed.append('avatar_url')
        if changed:
            profile.save(update_fields=changed)

    token = f'lf_g_{secrets.token_urlsafe(32)}'
    return Response({'success': True, 'token': token, 'user': UserProfileSerializer(profile).data})


@api_view(['POST'])
def verify_subscription_view(request):
    """Activates paid Verification Badge for Weekly (7d), Monthly (30d), or Yearly (365d)."""
    email = (request.data.get('email') or request.headers.get('X-User-Email') or '').strip().lower()
    plan = (request.data.get('plan') or '').strip().lower()
    if not email or plan not in ('weekly', 'monthly', 'yearly'):
        return Response(
            {'success': False, 'error': 'Valid email and plan (weekly, monthly, yearly) are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    profile = UserProfile.objects.filter(email__iexact=email).first()
    if not profile:
        return Response({'success': False, 'error': 'User profile not found.'}, status=status.HTTP_404_NOT_FOUND)

    days_map = {'weekly': 7, 'monthly': 30, 'yearly': 365}
    now = timezone.now()
    base_time = profile.verified_until if (profile.verified_until and profile.verified_until > now) else now
    profile.verified_plan = plan
    profile.verified_until = base_time + timedelta(days=days_map[plan])
    profile.save(update_fields=['verified_plan', 'verified_until', 'updated_at'])

    return Response({
        'success': True,
        'plan': plan,
        'verified_until': profile.verified_until.isoformat(),
        'user': UserProfileSerializer(profile).data,
    })


@api_view(['GET'])
def users_list_view(request):
    exclude_email = (request.query_params.get('excludeEmail') or '').strip().lower()
    viewer_email = (request.query_params.get('viewerEmail') or exclude_email or '').strip().lower()
    qs = UserProfile.objects.all().order_by('-created_at')
    if exclude_email:
        qs = qs.exclude(email__iexact=exclude_email)

    following_set = set()
    team_set = set()
    if viewer_email:
        following_set = set(
            e.lower() for e in UserFollow.objects.filter(follower_email__iexact=viewer_email).values_list('following_email', flat=True)
        )
        team_set = set(
            e.lower() for e in TeamMember.objects.filter(employer_email__iexact=viewer_email).values_list('employee_email', flat=True)
        )

    follower_counts = {}
    for fe in UserFollow.objects.values_list('following_email', flat=True):
        key = (fe or '').lower()
        follower_counts[key] = follower_counts.get(key, 0) + 1

    data = []
    for u in qs:
        item = UserProfileSerializer(u).data
        em = u.email.lower()
        item['is_following'] = em in following_set
        item['in_my_team'] = em in team_set
        item['followers_count'] = follower_counts.get(em, 0)
        data.append(item)
    return Response({'success': True, 'users': data})


@api_view(['GET', 'PUT', 'PATCH'])
def profile_view(request):
    email = (
        request.query_params.get('email')
        or request.headers.get('X-User-Email')
        or request.data.get('email')
        or ''
    ).strip().lower()

    profile = UserProfile.objects.filter(email=email).first() if email else UserProfile.objects.first()
    if not profile:
        return Response({'success': False, 'error': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response({'success': True, 'profile': UserProfileSerializer(profile).data})

    # Prevent manual location spoofing via /api/profile/ (location is auto-locked via device GPS /api/location/update/)
    payload = dict(request.data)
    for locked_field in ('city', 'exact_address', 'latitude', 'longitude', 'gps_accuracy', 'location_updated_at'):
        payload.pop(locked_field, None)

    serializer = UserProfileSerializer(profile, data=payload, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response({'success': True, 'profile': serializer.data})
    return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def update_gps_location_view(request):
    """Stores exact real-time GPS coordinates & reverse-geocoded street address from the user's device."""
    email = (request.data.get('email') or request.headers.get('X-User-Email') or '').strip().lower()
    if not email:
        return Response({'success': False, 'error': 'User email is required.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        lat = float(request.data.get('latitude'))
        lng = float(request.data.get('longitude'))
    except (TypeError, ValueError):
        return Response({'success': False, 'error': 'Valid latitude and longitude are required.'}, status=status.HTTP_400_BAD_REQUEST)

    exact_address = (request.data.get('exact_address') or '').strip()
    city = (request.data.get('city') or '').strip()
    country_code = (request.data.get('country_code') or '').strip().upper()
    accuracy = None
    if request.data.get('accuracy') is not None:
        try:
            accuracy = float(request.data.get('accuracy'))
        except (TypeError, ValueError):
            accuracy = None

    profile = UserProfile.objects.filter(email__iexact=email).first()
    if not profile:
        return Response({'success': False, 'error': 'User profile not found.'}, status=status.HTTP_404_NOT_FOUND)

    profile.latitude = lat
    profile.longitude = lng
    if exact_address:
        profile.exact_address = exact_address
    if city:
        profile.city = city
    if country_code:
        profile.country_code = country_code[:8]
    if accuracy is not None:
        profile.gps_accuracy = accuracy
    profile.location_updated_at = timezone.now()
    profile.save()

    LocationLog.objects.create(
        user=profile,
        email=profile.email,
        latitude=lat,
        longitude=lng,
        exact_address=exact_address or profile.exact_address,
        city=city or profile.city,
        country_code=country_code or profile.country_code,
        accuracy=accuracy,
    )

    return Response({'success': True, 'user': UserProfileSerializer(profile).data})


@api_view(['GET'])
def location_history_view(request):
    """Returns stored GPS check-in history for a specific employee email (for employer audit)."""
    email = (request.query_params.get('email') or '').strip().lower()
    qs = LocationLog.objects.all()
    if email:
        qs = qs.filter(email__iexact=email)
    logs = [
        {
            'id': log.id,
            'email': log.email,
            'latitude': log.latitude,
            'longitude': log.longitude,
            'exact_address': log.exact_address,
            'city': log.city,
            'country_code': log.country_code,
            'accuracy': log.accuracy,
            'recorded_at': log.recorded_at.isoformat(),
        }
        for log in qs[:50]
    ]
    return Response({'success': True, 'count': len(logs), 'history': logs})


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def media_upload_view(request):
    uploaded = request.FILES.get('file')
    if not uploaded:
        return Response({'success': False, 'error': 'No file provided.'}, status=status.HTTP_400_BAD_REQUEST)

    raw_bytes = uploaded.read()
    ext = os.path.splitext(uploaded.name)[1].lower() or '.bin'
    uuid_key = f'lf_{secrets.token_hex(10)}'
    safe_name = f'{uuid_key}{ext}'
    content_type = uploaded.content_type or mimetypes.guess_type(safe_name)[0] or 'application/octet-stream'

    # Store permanently in database (persists across Render restarts when backed by PostgreSQL!)
    StoredMedia.objects.create(
        uuid_key=uuid_key,
        filename=safe_name,
        content_type=content_type,
        data=raw_bytes,
        size=len(raw_bytes),
    )

    rel_url = f'{settings.MEDIA_URL}db/{uuid_key}/{safe_name}'
    abs_url = request.build_absolute_uri(rel_url)
    if 'onrender.com' in abs_url and abs_url.startswith('http://'):
        abs_url = abs_url.replace('http://', 'https://', 1)
    return Response({'success': True, 'url': abs_url, 'filename': safe_name}, status=status.HTTP_201_CREATED)


@api_view(['GET', 'POST'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def feed_view(request):
    if request.method == 'GET':
        user_email = (request.query_params.get('email') or '').strip().lower()
        posts = FeedPost.objects.all()
        liked_ids = set()
        if user_email:
            liked_ids = set(PostLike.objects.filter(user_email=user_email).values_list('post_id', flat=True))
        serialized = []
        now = timezone.now()
        profiles_by_email = {
            p.email.lower(): p for p in UserProfile.objects.all()
        }
        following_set = set()
        team_set = set()
        if user_email:
            following_set = set(
                e.lower() for e in UserFollow.objects.filter(follower_email__iexact=user_email).values_list('following_email', flat=True)
            )
            team_set = set(
                e.lower() for e in TeamMember.objects.filter(employer_email__iexact=user_email).values_list('employee_email', flat=True)
            )
        follower_counts = {}
        for fe in UserFollow.objects.values_list('following_email', flat=True):
            k = (fe or '').lower()
            follower_counts[k] = follower_counts.get(k, 0) + 1

        for post in posts:
            item = FeedPostSerializer(post).data
            item['liked_by_me'] = post.id in liked_ids
            em = (post.author_email or '').lower()
            author_prof = profiles_by_email.get(em)
            is_company = bool(
                author_prof and (author_prof.is_company_verified or author_prof.email.lower().endswith('@localfix.com'))
            )
            is_paid = bool(author_prof and author_prof.verified_until and author_prof.verified_until > now)
            item['author_is_verified'] = is_company or is_paid
            item['author_is_company'] = is_company
            item['author_is_following'] = em in following_set
            item['author_in_my_team'] = em in team_set
            item['author_followers_count'] = follower_counts.get(em, 0)
            if author_prof and author_prof.avatar_url:
                item['author_avatar'] = author_prof.avatar_url
            serialized.append(item)
        return Response({'success': True, 'posts': serialized})

    serializer = FeedPostSerializer(data=request.data)
    if serializer.is_valid():
        post = serializer.save()
        data = FeedPostSerializer(post).data
        data['liked_by_me'] = False
        return Response({'success': True, 'post': data}, status=status.HTTP_201_CREATED)
    return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def feed_toggle_like(request, post_id):
    post = FeedPost.objects.filter(id=post_id).first()
    if not post:
        return Response({'success': False, 'error': 'Post not found.'}, status=status.HTTP_404_NOT_FOUND)
    user_email = (request.data.get('email') or 'guest@localfix.com').strip().lower()
    existing = PostLike.objects.filter(post=post, user_email=user_email).first()
    if existing:
        existing.delete()
        liked = False
    else:
        PostLike.objects.create(post=post, user_email=user_email)
        liked = True
    post.likes = PostLike.objects.filter(post=post).count()
    post.save(update_fields=['likes'])
    return Response({'success': True, 'liked': liked, 'likes': post.likes})


@api_view(['GET', 'POST'])
def feed_comments_view(request, post_id):
    post = FeedPost.objects.filter(id=post_id).first()
    if not post:
        return Response({'success': False, 'error': 'Post not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        comments = PostComment.objects.filter(post=post)
        return Response({'success': True, 'comments': PostCommentSerializer(comments, many=True).data})

    text = (request.data.get('text') or '').strip()
    if not text:
        return Response({'success': False, 'error': 'Comment text cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

    parent_comment = None
    raw_parent = request.data.get('parent_id') or request.data.get('parent')
    if raw_parent not in (None, ''):
        try:
            parent_comment = PostComment.objects.filter(id=int(raw_parent), post=post).first()
            if parent_comment and parent_comment.parent_id:
                parent_comment = parent_comment.parent
        except (ValueError, TypeError):
            parent_comment = None

    comment = PostComment.objects.create(
        post=post,
        parent=parent_comment,
        author_name=(request.data.get('author_name') or 'LocalFix User').strip(),
        author_email=(request.data.get('author_email') or '').strip().lower(),
        author_avatar=(request.data.get('author_avatar') or '').strip(),
        text=text,
    )
    post.comments_count = PostComment.objects.filter(post=post).count()
    post.save(update_fields=['comments_count'])
    return Response(
        {'success': True, 'comment': PostCommentSerializer(comment).data, 'comments_count': post.comments_count},
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'POST'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def reels_view(request):
    if request.method == 'GET':
        user_email = (request.query_params.get('email') or '').strip().lower()
        reels = VideoReel.objects.all()
        liked_ids = set()
        if user_email:
            liked_ids = set(ReelLike.objects.filter(user_email=user_email).values_list('reel_id', flat=True))
        serialized = []
        for reel in reels:
            item = VideoReelSerializer(reel).data
            item['liked_by_me'] = reel.id in liked_ids
            serialized.append(item)
        return Response({'success': True, 'reels': serialized})

    serializer = VideoReelSerializer(data=request.data)
    if serializer.is_valid():
        reel = serializer.save()
        data = VideoReelSerializer(reel).data
        data['liked_by_me'] = False
        return Response({'success': True, 'reel': data}, status=status.HTTP_201_CREATED)
    return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def reel_toggle_like(request, reel_id):
    reel = VideoReel.objects.filter(id=reel_id).first()
    if not reel:
        return Response({'success': False, 'error': 'Reel not found.'}, status=status.HTTP_404_NOT_FOUND)
    user_email = (request.data.get('email') or 'guest@localfix.com').strip().lower()
    existing = ReelLike.objects.filter(reel=reel, user_email=user_email).first()
    if existing:
        existing.delete()
        liked = False
    else:
        ReelLike.objects.create(reel=reel, user_email=user_email)
        liked = True
    reel.likes = ReelLike.objects.filter(reel=reel).count()
    reel.save(update_fields=['likes'])
    return Response({'success': True, 'liked': liked, 'likes': reel.likes})


@api_view(['GET', 'POST'])
def reel_comments_view(request, reel_id):
    reel = VideoReel.objects.filter(id=reel_id).first()
    if not reel:
        return Response({'success': False, 'error': 'Reel not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        comments = ReelComment.objects.filter(reel=reel)
        return Response({'success': True, 'comments': ReelCommentSerializer(comments, many=True).data})

    text = (request.data.get('text') or '').strip()
    if not text:
        return Response({'success': False, 'error': 'Comment text cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

    parent_comment = None
    raw_parent = request.data.get('parent_id') or request.data.get('parent')
    if raw_parent not in (None, ''):
        try:
            parent_comment = ReelComment.objects.filter(id=int(raw_parent), reel=reel).first()
            if parent_comment and parent_comment.parent_id:
                parent_comment = parent_comment.parent
        except (ValueError, TypeError):
            parent_comment = None

    comment = ReelComment.objects.create(
        reel=reel,
        parent=parent_comment,
        author_name=(request.data.get('author_name') or 'LocalFix User').strip(),
        author_email=(request.data.get('author_email') or '').strip().lower(),
        text=text,
    )
    reel.comments_count = ReelComment.objects.filter(reel=reel).count()
    reel.save(update_fields=['comments_count'])
    return Response(
        {'success': True, 'comment': ReelCommentSerializer(comment).data, 'comments_count': reel.comments_count},
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET'])
def chat_conversations_view(request):
    my_email = (request.query_params.get('email') or '').strip().lower()
    if not my_email:
        return Response({'success': True, 'conversations': []})

    msgs = ChatMessage.objects.filter(
        Q(sender_email__iexact=my_email) | Q(receiver_email__iexact=my_email)
    ).order_by('-created_at')

    seen = {}
    for m in msgs:
        other_email = m.receiver_email.lower() if m.sender_email.lower() == my_email else m.sender_email.lower()
        other_name = m.receiver_name if m.sender_email.lower() == my_email else m.sender_name
        if other_email not in seen:
            profile = UserProfile.objects.filter(email__iexact=other_email).first()
            preview = m.text
            if not preview:
                if m.message_type == 'image':
                    preview = '📷 Photo'
                elif m.message_type == 'voice':
                    preview = f'🎤 Voice note ({m.audio_duration_sec}s)'
            is_verified = False
            if profile:
                is_verified = bool(
                    profile.is_company_verified
                    or profile.email.lower().endswith('@localfix.com')
                    or (profile.verified_until and profile.verified_until > timezone.now())
                )
            seen[other_email] = {
                'counterpart_email': other_email,
                'counterpart_name': 'Saved Messages (You)' if other_email == my_email else (profile.name if profile else other_name),
                'counterpart_role': profile.trade if profile else 'Member',
                'counterpart_avatar': profile.avatar_url if profile else '',
                'counterpart_is_verified': is_verified,
                'last_message': preview,
                'last_message_time': m.created_at.isoformat(),
            }

    return Response({'success': True, 'conversations': list(seen.values())})


@api_view(['GET', 'POST'])
def chat_messages_view(request):
    if request.method == 'GET':
        u1 = (request.query_params.get('user1') or '').strip().lower()
        u2 = (request.query_params.get('user2') or '').strip().lower()
        if not u1 or not u2:
            return Response({'success': True, 'messages': []})
        qs = ChatMessage.objects.filter(
            (Q(sender_email__iexact=u1) & Q(receiver_email__iexact=u2))
            | (Q(sender_email__iexact=u2) & Q(receiver_email__iexact=u1))
        ).order_by('created_at')
        return Response({'success': True, 'messages': ChatMessageSerializer(qs, many=True).data})

    sender_email = (request.data.get('sender_email') or '').strip().lower()
    receiver_email = (request.data.get('receiver_email') or '').strip().lower()
    text = (request.data.get('text') or '').strip()
    message_type = (request.data.get('message_type') or 'text').strip().lower()
    media_url = (request.data.get('media_url') or '').strip()
    try:
        audio_duration_sec = int(request.data.get('audio_duration_sec') or 0)
    except (TypeError, ValueError):
        audio_duration_sec = 0

    if not sender_email or not receiver_email or (not text and not media_url):
        return Response(
            {'success': False, 'error': 'sender_email, receiver_email, and text or media_url are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    msg = ChatMessage.objects.create(
        sender_email=sender_email,
        sender_name=(request.data.get('sender_name') or sender_email.split('@')[0]).strip(),
        receiver_email=receiver_email,
        receiver_name=(request.data.get('receiver_name') or receiver_email.split('@')[0]).strip(),
        text=text,
        message_type=message_type if message_type in ('text', 'image', 'voice') else 'text',
        media_url=media_url,
        audio_duration_sec=audio_duration_sec,
    )
    return Response({'success': True, 'message': ChatMessageSerializer(msg).data}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
def nearby_artisans_view(request):
    city = (request.query_params.get('city') or '').strip()
    exclude_email = (request.query_params.get('excludeEmail') or '').strip().lower()
    qs = UserProfile.objects.all().order_by('-created_at')
    if exclude_email:
        qs = qs.exclude(email__iexact=exclude_email)
    if city:
        city_matches = qs.filter(city__icontains=city.split(',')[0].strip())
        if city_matches.exists():
            qs = city_matches
    return Response({
        'success': True,
        'count': qs.count(),
        'artisans': UserProfileSerializer(qs, many=True).data,
    })


@api_view(['GET'])
def escrow_summary_view(request):
    contracts = EscrowContract.objects.all()
    total = sum(float(c.amount_usd) for c in contracts)
    return Response({
        'success': True,
        'vault_balance_usd': total,
        'active_contracts': contracts.count(),
        'contracts': EscrowContractSerializer(contracts, many=True).data,
    })


def _serialize_call(call):
    try:
        offer = json.loads(call.offer_sdp) if call.offer_sdp else None
    except Exception:
        offer = None
    try:
        answer = json.loads(call.answer_sdp) if call.answer_sdp else None
    except Exception:
        answer = None
    try:
        caller_cands = json.loads(call.caller_candidates) if call.caller_candidates else []
    except Exception:
        caller_cands = []
    try:
        callee_cands = json.loads(call.callee_candidates) if call.callee_candidates else []
    except Exception:
        callee_cands = []

    return {
        'id': call.id,
        'caller_email': call.caller_email,
        'caller_name': call.caller_name,
        'caller_avatar': call.caller_avatar,
        'callee_email': call.callee_email,
        'callee_name': call.callee_name,
        'callee_avatar': call.callee_avatar,
        'is_video': call.is_video,
        'status': call.status,
        'offer': offer,
        'answer': answer,
        'caller_candidates': caller_cands,
        'callee_candidates': callee_cands,
        'created_at': call.created_at.isoformat(),
    }


@api_view(['POST'])
def call_start_view(request):
    caller_email = (request.data.get('caller_email') or '').strip().lower()
    callee_email = (request.data.get('callee_email') or '').strip().lower()
    offer = request.data.get('offer')
    if not caller_email or not callee_email or not offer:
        return Response(
            {'success': False, 'error': 'caller_email, callee_email, and WebRTC offer are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # End any previous stale ringing calls between the same peers
    CallSession.objects.filter(
        caller_email__iexact=caller_email,
        callee_email__iexact=callee_email,
        status='ringing',
    ).update(status='ended')

    call = CallSession.objects.create(
        caller_email=caller_email,
        caller_name=(request.data.get('caller_name') or caller_email.split('@')[0]).strip(),
        caller_avatar=(request.data.get('caller_avatar') or '').strip(),
        callee_email=callee_email,
        callee_name=(request.data.get('callee_name') or callee_email.split('@')[0]).strip(),
        callee_avatar=(request.data.get('callee_avatar') or '').strip(),
        is_video=bool(request.data.get('is_video', True)),
        status='ringing',
        offer_sdp=json.dumps(offer),
    )
    return Response({'success': True, 'call': _serialize_call(call)}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
def call_incoming_view(request):
    email = (request.query_params.get('email') or '').strip().lower()
    if not email:
        return Response({'success': True, 'call': None})
    cutoff = timezone.now() - timedelta(seconds=90)
    call = CallSession.objects.filter(
        callee_email__iexact=email,
        status='ringing',
        created_at__gte=cutoff,
    ).first()
    return Response({'success': True, 'call': _serialize_call(call) if call else None})


@api_view(['GET'])
def call_detail_view(request, call_id):
    call = CallSession.objects.filter(id=call_id).first()
    if not call:
        return Response({'success': False, 'error': 'Call not found.'}, status=status.HTTP_404_NOT_FOUND)
    return Response({'success': True, 'call': _serialize_call(call)})


@api_view(['POST'])
def call_answer_view(request, call_id):
    call = CallSession.objects.filter(id=call_id).first()
    if not call:
        return Response({'success': False, 'error': 'Call not found.'}, status=status.HTTP_404_NOT_FOUND)
    answer = request.data.get('answer')
    if not answer:
        return Response({'success': False, 'error': 'WebRTC answer is required.'}, status=status.HTTP_400_BAD_REQUEST)
    call.answer_sdp = json.dumps(answer)
    call.status = 'accepted'
    call.save(update_fields=['answer_sdp', 'status', 'updated_at'])
    return Response({'success': True, 'call': _serialize_call(call)})


@api_view(['POST'])
def call_ice_view(request, call_id):
    call = CallSession.objects.filter(id=call_id).first()
    if not call:
        return Response({'success': False, 'error': 'Call not found.'}, status=status.HTTP_404_NOT_FOUND)
    role = (request.data.get('role') or 'caller').strip().lower()
    candidate = request.data.get('candidate')
    if not candidate:
        return Response({'success': False, 'error': 'ICE candidate is required.'}, status=status.HTTP_400_BAD_REQUEST)

    field = 'caller_candidates' if role == 'caller' else 'callee_candidates'
    try:
        current = json.loads(getattr(call, field) or '[]')
    except Exception:
        current = []
    current.append(candidate)
    setattr(call, field, json.dumps(current))
    call.save(update_fields=[field, 'updated_at'])
    return Response({'success': True, 'count': len(current)})


@api_view(['POST'])
def call_end_view(request, call_id):
    call = CallSession.objects.filter(id=call_id).first()
    if not call:
        return Response({'success': False, 'error': 'Call not found.'}, status=status.HTTP_404_NOT_FOUND)
    new_status = (request.data.get('status') or 'ended').strip().lower()
    if new_status not in ('ended', 'rejected'):
        new_status = 'ended'
    call.status = new_status
    call.save(update_fields=['status', 'updated_at'])
    return Response({'success': True, 'status': call.status})


# ---- 24-HOUR WORK & JOB STORIES ----

def _serialize_story(story, profiles_by_email, following_set, now):
    em = (story.author_email or '').lower()
    prof = profiles_by_email.get(em)
    is_company = bool(prof and (prof.is_company_verified or prof.email.lower().endswith('@localfix.com')))
    is_paid = bool(prof and prof.verified_until and prof.verified_until > now)
    remaining_sec = max(0, int((story.expires_at - now).total_seconds()))
    return {
        'id': story.id,
        'author_email': story.author_email,
        'author_name': prof.name if prof else story.author_name,
        'author_avatar': (prof.avatar_url if prof and prof.avatar_url else story.author_avatar),
        'author_role': (prof.trade if prof and prof.trade else story.author_role),
        'author_is_verified': is_company or is_paid,
        'author_is_company': is_company,
        'author_is_following': em in following_set,
        'media_url': story.media_url,
        'is_video': story.is_video,
        'caption': story.caption,
        'location': story.location,
        'views_count': story.views_count,
        'created_at': story.created_at.isoformat(),
        'expires_at': story.expires_at.isoformat(),
        'remaining_hours': max(1, remaining_sec // 3600),
    }


@api_view(['GET', 'POST'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def stories_view(request):
    now = timezone.now()
    if request.method == 'GET':
        viewer_email = (request.query_params.get('email') or '').strip().lower()
        active_stories = UserStory.objects.filter(expires_at__gt=now).order_by('-created_at')
        profiles_by_email = {p.email.lower(): p for p in UserProfile.objects.all()}
        following_set = set()
        if viewer_email:
            following_set = set(
                e.lower() for e in UserFollow.objects.filter(follower_email__iexact=viewer_email).values_list('following_email', flat=True)
            )
        items = [_serialize_story(s, profiles_by_email, following_set, now) for s in active_stories]
        return Response({'success': True, 'stories': items})

    author_email = (request.data.get('author_email') or '').strip().lower()
    media_url = (request.data.get('media_url') or '').strip()
    caption = (request.data.get('caption') or '').strip()
    if not author_email or (not media_url and not caption):
        return Response(
            {'success': False, 'error': 'author_email and either media_url or caption are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    story = UserStory.objects.create(
        author_email=author_email,
        author_name=(request.data.get('author_name') or author_email.split('@')[0]).strip(),
        author_avatar=(request.data.get('author_avatar') or '').strip(),
        author_role=(request.data.get('author_role') or 'Member').strip(),
        media_url=media_url,
        is_video=bool(request.data.get('is_video', False)),
        caption=caption,
        location=(request.data.get('location') or '').strip(),
        expires_at=now + timedelta(hours=24),
    )
    profiles_by_email = {p.email.lower(): p for p in UserProfile.objects.filter(email__iexact=author_email)}
    return Response(
        {'success': True, 'story': _serialize_story(story, profiles_by_email, set(), now)},
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
def story_mark_view(request, story_id):
    story = UserStory.objects.filter(id=story_id).first()
    if not story:
        return Response({'success': False, 'error': 'Story not found.'}, status=status.HTTP_404_NOT_FOUND)
    story.views_count += 1
    story.save(update_fields=['views_count'])
    return Response({'success': True, 'views_count': story.views_count})


@api_view(['DELETE'])
def story_delete_view(request, story_id):
    story = UserStory.objects.filter(id=story_id).first()
    if not story:
        return Response({'success': False, 'error': 'Story not found.'}, status=status.HTTP_404_NOT_FOUND)
    story.delete()
    return Response({'success': True})


# ---- FOLLOW PRO ----

@api_view(['POST'])
def follow_toggle_view(request):
    follower = (request.data.get('follower_email') or '').strip().lower()
    following = (request.data.get('following_email') or '').strip().lower()
    if not follower or not following or follower == following:
        return Response(
            {'success': False, 'error': 'Valid distinct follower_email and following_email are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    existing = UserFollow.objects.filter(follower_email__iexact=follower, following_email__iexact=following).first()
    if existing:
        existing.delete()
        is_following = False
    else:
        UserFollow.objects.create(follower_email=follower, following_email=following)
        is_following = True

    followers_count = UserFollow.objects.filter(following_email__iexact=following).count()
    following_count = UserFollow.objects.filter(follower_email__iexact=follower).count()
    return Response({
        'success': True,
        'is_following': is_following,
        'followers_count': followers_count,
        'following_count': following_count,
    })


# ---- EMPLOYER'S "MY TEAM" ----

@api_view(['GET'])
def team_list_view(request):
    employer_email = (request.query_params.get('employer_email') or '').strip().lower()
    if not employer_email:
        return Response({'success': True, 'team': []})
    members = TeamMember.objects.filter(employer_email__iexact=employer_email)
    emails = [m.employee_email.lower() for m in members]
    profiles = {p.email.lower(): p for p in UserProfile.objects.filter(email__in=emails)}
    result = []
    for m in members:
        p = profiles.get(m.employee_email.lower())
        if p:
            item = UserProfileSerializer(p).data
            item['team_label'] = m.label
            item['in_my_team'] = True
            result.append(item)
    return Response({'success': True, 'count': len(result), 'team': result})


@api_view(['POST'])
def team_toggle_view(request):
    employer = (request.data.get('employer_email') or '').strip().lower()
    employee = (request.data.get('employee_email') or '').strip().lower()
    label = (request.data.get('label') or 'Team Employee').strip()
    if not employer or not employee or employer == employee:
        return Response(
            {'success': False, 'error': 'Valid distinct employer_email and employee_email are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    existing = TeamMember.objects.filter(employer_email__iexact=employer, employee_email__iexact=employee).first()
    if existing:
        existing.delete()
        in_team = False
    else:
        TeamMember.objects.create(employer_email=employer, employee_email=employee, label=label)
        in_team = True

    team_count = TeamMember.objects.filter(employer_email__iexact=employer).count()
    return Response({'success': True, 'in_team': in_team, 'team_count': team_count})
