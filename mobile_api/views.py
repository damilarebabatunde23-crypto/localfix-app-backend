from datetime import timedelta
import base64
import json
import mimetypes
import os
import re
import secrets
import urllib.parse
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
    StoryView,
    PaymentTransaction,
    ContentModerationLog,
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


# ---- REAL PAYMENT VERIFICATION (PAYSTACK / STRIPE — NO FREE BADGES) ----

PLAN_PRICING = {
    'weekly': {'days': 7, 'usd_cents': 299, 'ngn_kobo': 450000, 'label': 'Weekly Verified (7 Days)'},
    'monthly': {'days': 30, 'usd_cents': 899, 'ngn_kobo': 1350000, 'label': 'Monthly Verified (30 Days)'},
    'yearly': {'days': 365, 'usd_cents': 7999, 'ngn_kobo': 12000000, 'label': 'Yearly Verified (365 Days)'},
}


@api_view(['POST'])
def subscription_checkout_view(request):
    """Creates a REAL Paystack or Stripe checkout link for Weekly / Monthly / Yearly Verification Badge."""
    email = (request.data.get('email') or request.headers.get('X-User-Email') or '').strip().lower()
    plan = (request.data.get('plan') or '').strip().lower()
    currency = (request.data.get('currency') or 'USD').strip().upper()
    if not email or plan not in PLAN_PRICING:
        return Response(
            {'success': False, 'error': 'Valid email and plan (weekly, monthly, yearly) are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    profile = UserProfile.objects.filter(email__iexact=email).first()
    if not profile:
        return Response({'success': False, 'error': 'User account not found.'}, status=status.HTTP_404_NOT_FOUND)

    pricing = PLAN_PRICING[plan]
    paystack_key = os.environ.get('PAYSTACK_SECRET_KEY', '').strip()
    stripe_key = os.environ.get('STRIPE_SECRET_KEY', '').strip()

    # 1. Real Paystack Checkout
    if paystack_key:
        ref = f'lf_ps_{plan}_{secrets.token_hex(8)}'
        amount_kobo = pricing['ngn_kobo'] if currency == 'NGN' else pricing['usd_cents']
        use_curr = 'NGN' if currency == 'NGN' else 'USD'
        payload = json.dumps({
            'email': email,
            'amount': amount_kobo,
            'currency': use_curr,
            'reference': ref,
            'metadata': {'plan': plan, 'email': email, 'app': 'LocalFix'},
        }).encode('utf-8')
        try:
            req = urllib.request.Request(
                'https://api.paystack.co/transaction/initialize',
                data=payload,
                headers={
                    'Authorization': f'Bearer {paystack_key}',
                    'Content-Type': 'application/json',
                },
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            if data.get('status') is True and data.get('data', {}).get('authorization_url'):
                PaymentTransaction.objects.create(
                    user_email=email,
                    plan=plan,
                    provider='paystack',
                    reference=ref,
                    amount_minor=amount_kobo,
                    currency=use_curr,
                    status='pending',
                )
                return Response({
                    'success': True,
                    'provider': 'paystack',
                    'reference': ref,
                    'checkout_url': data['data']['authorization_url'],
                })
        except Exception as exc:
            return Response(
                {'success': False, 'error': f'Paystack initialization failed: {exc}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

    # 2. Real Stripe Checkout
    if stripe_key:
        ref = f'lf_st_{plan}_{secrets.token_hex(8)}'
        form_data = urllib.parse.urlencode({
            'mode': 'payment',
            'customer_email': email,
            'success_url': 'https://localfix-app-backend.onrender.com/?payment=success',
            'cancel_url': 'https://localfix-app-backend.onrender.com/?payment=cancelled',
            'line_items[0][price_data][currency]': 'usd',
            'line_items[0][price_data][unit_amount]': str(pricing['usd_cents']),
            'line_items[0][price_data][product_data][name]': f"LocalFix {pricing['label']}",
            'line_items[0][quantity]': '1',
            'client_reference_id': ref,
        }).encode('utf-8')
        auth_b64 = base64.b64encode(f'{stripe_key}:'.encode('utf-8')).decode('ascii')
        try:
            req = urllib.request.Request(
                'https://api.stripe.com/v1/checkout/sessions',
                data=form_data,
                headers={
                    'Authorization': f'Basic {auth_b64}',
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            session_id = data.get('id')
            checkout_url = data.get('url')
            if session_id and checkout_url:
                PaymentTransaction.objects.create(
                    user_email=email,
                    plan=plan,
                    provider='stripe',
                    reference=session_id,
                    amount_minor=pricing['usd_cents'],
                    currency='USD',
                    status='pending',
                )
                return Response({
                    'success': True,
                    'provider': 'stripe',
                    'reference': session_id,
                    'checkout_url': checkout_url,
                })
        except Exception as exc:
            return Response(
                {'success': False, 'error': f'Stripe checkout failed: {exc}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

    # Strict: NEVER grant a verification badge without real payment gateway!
    return Response(
        {
            'success': False,
            'payment_gateway_required': True,
            'error': 'Real payment is required for Verification Badges. Set PAYSTACK_SECRET_KEY or STRIPE_SECRET_KEY in Render Environment Variables to accept live payments.',
        },
        status=status.HTTP_402_PAYMENT_REQUIRED,
    )


@api_view(['POST'])
def verify_subscription_view(request):
    """Strictly verifies real Paystack / Stripe payment BEFORE activating Weekly/Monthly/Yearly badge."""
    email = (request.data.get('email') or request.headers.get('X-User-Email') or '').strip().lower()
    plan = (request.data.get('plan') or '').strip().lower()
    reference = (request.data.get('reference') or request.data.get('payment_reference') or '').strip()
    provider = (request.data.get('provider') or 'paystack').strip().lower()

    if not email or plan not in PLAN_PRICING or not reference:
        return Response(
            {'success': False, 'error': 'Real payment reference, email, and valid plan are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    profile = UserProfile.objects.filter(email__iexact=email).first()
    if not profile:
        return Response({'success': False, 'error': 'User profile not found.'}, status=status.HTTP_404_NOT_FOUND)

    tx = PaymentTransaction.objects.filter(reference=reference, user_email__iexact=email).first()
    if tx and tx.status == 'paid':
        return Response({
            'success': True,
            'plan': tx.plan,
            'verified_until': profile.verified_until.isoformat() if profile.verified_until else '',
            'user': UserProfileSerializer(profile).data,
        })

    paid_confirmed = False
    paystack_key = os.environ.get('PAYSTACK_SECRET_KEY', '').strip()
    stripe_key = os.environ.get('STRIPE_SECRET_KEY', '').strip()

    if provider == 'paystack' and paystack_key:
        try:
            req = urllib.request.Request(
                f'https://api.paystack.co/transaction/verify/{urllib.parse.quote(reference)}',
                headers={'Authorization': f'Bearer {paystack_key}'},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            tx_data = data.get('data') or {}
            if data.get('status') is True and tx_data.get('status') == 'success':
                paid_confirmed = True
        except Exception:
            paid_confirmed = False
    elif provider == 'stripe' and stripe_key:
        try:
            auth_b64 = base64.b64encode(f'{stripe_key}:'.encode('utf-8')).decode('ascii')
            req = urllib.request.Request(
                f'https://api.stripe.com/v1/checkout/sessions/{urllib.parse.quote(reference)}',
                headers={'Authorization': f'Basic {auth_b64}'},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            if data.get('payment_status') == 'paid':
                paid_confirmed = True
        except Exception:
            paid_confirmed = False

    if not paid_confirmed:
        return Response(
            {
                'success': False,
                'error': 'Payment not confirmed yet. Complete checkout first, then tap Verify Payment.',
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )

    now = timezone.now()
    days = PLAN_PRICING[plan]['days']
    base_time = profile.verified_until if (profile.verified_until and profile.verified_until > now) else now
    profile.verified_plan = plan
    profile.verified_until = base_time + timedelta(days=days)
    profile.save(update_fields=['verified_plan', 'verified_until', 'updated_at'])

    if tx:
        tx.status = 'paid'
        tx.verified_at = now
        tx.save(update_fields=['status', 'verified_at'])

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


# ---- STRICT FIXES-ONLY CONTENT MODERATION (WARNING -> 7-DAY LOCK -> 30-DAY LOCK) ----

NON_FIX_BLOCKED_TERMS = {
    'dance', 'dancing', 'twerk', 'twerking', 'party', 'clubbing', 'selfie', 'meme', 'memes',
    'comedy', 'prank', 'skit', 'music video', 'song', 'rap', 'betting', 'gambling', 'casino',
    'bitcoin', 'crypto', 'forex', 'giveaway', 'hookup', 'dating', 'nude', 'naked', 'porn',
    'sexy', 'bikini', 'fashion', 'makeup', 'outfit', 'ootd', 'recipe', 'cooking', 'mukbang',
    'football match', 'soccer highlights', 'movie trailer', 'netflix', 'gaming', 'fortnite',
    'pubg', 'tiktok trend', 'challenge', 'politics', 'election', 'gossip', 'celebrity',
}

FIX_RELEVANT_TERMS = {
    'fix', 'fixed', 'fixing', 'repair', 'repaired', 'repairing', 'install', 'installed',
    'installation', 'maintenance', 'service', 'servicing', 'troubleshoot', 'diagnose',
    'diagnostic', 'replace', 'replacement', 'upgrade', 'mount', 'mounted', 'wire', 'wiring',
    'electrical', 'electrician', 'solar', 'inverter', 'battery', 'panel', 'breaker', 'socket',
    'switch', 'voltage', 'light', 'lighting', 'plumbing', 'plumber', 'pipe', 'leak', 'leaking',
    'tap', 'faucet', 'sink', 'toilet', 'drain', 'pump', 'heater', 'boiler', 'water', 'ac',
    'aircon', 'air conditioner', 'hvac', 'cooling', 'compressor', 'fridge', 'freezer',
    'generator', 'gen', 'mechanic', 'auto', 'car', 'engine', 'brake', 'brakes', 'tire', 'tyre',
    'oil change', 'transmission', 'carpenter', 'carpentry', 'wood', 'door', 'cabinet', 'furniture',
    'roof', 'roofing', 'ceiling', 'tile', 'tiling', 'paint', 'painting', 'plaster', 'wall',
    'weld', 'welding', 'gate', 'fence', 'lock', 'locksmith', 'window', 'glass', 'phone repair',
    'screen', 'laptop', 'computer', 'tv', 'television', 'appliance', 'washer', 'washing machine',
    'microwave', 'oven', 'cctv', 'camera install', 'smart home', 'router', 'wifi', 'network',
    'renovation', 'remodel', 'construction', 'masonry', 'concrete', 'tool', 'tools', 'artisan',
    'technician', 'handyman', 'work', 'job', 'project', 'quote', 'inspection', 'before and after',
    'broken', 'fault', 'faulty', 'damaged', 'crack', 'cracked', 'clogged', 'blocked', 'cleaning',
}


def _moderate_fixes_only_content(user_email, text, content_type, category=''):
    """
    Enforces LocalFix Fixes-Only Policy:
    - If account is already locked -> 403 block.
    - If content is NOT about fixes/repairs/trades:
      * 1st offense: WARNING before locking (content NOT published).
      * 2nd offense: Account LOCKED for 7 DAYS (content NOT published).
      * 3rd+ offense: Account LOCKED for 30 DAYS / 1 MONTH (content NOT published).
    Returns None if allowed, or a DRF Response if blocked.
    """
    now = timezone.now()
    profile = UserProfile.objects.filter(email__iexact=user_email).first() if user_email else None

    if profile and profile.locked_until and profile.locked_until > now:
        unlock_str = profile.locked_until.strftime('%Y-%m-%d %H:%M UTC')
        return Response(
            {
                'success': False,
                'moderation_action': 'already_locked',
                'locked_until': profile.locked_until.isoformat(),
                'error': f'Your account is locked until {unlock_str} due to posting non-fix content ({profile.lock_reason}).',
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    combined = f'{text or ""}'.lower().strip()
    has_blocked = any(re.search(r'\b' + re.escape(term) + r'\b', combined) for term in NON_FIX_BLOCKED_TERMS)
    has_fix_keyword = any(re.search(r'\b' + re.escape(term) + r'\b', combined) for term in FIX_RELEVANT_TERMS)

    # Also ignore default auto-generated filler if user typed an off-topic caption
    is_violation = has_blocked or (len(combined) > 0 and not has_fix_keyword)

    # Optional Gemini AI verification when GEMINI_API_KEY is configured on Render
    gemini_key = os.environ.get('GEMINI_API_KEY', '').strip()
    if gemini_key and combined:
        try:
            prompt = (
                'You are LocalFix content moderator. LocalFix ONLY allows posts/videos/stories about real '
                'repairs, fixes, maintenance, installations, construction, home/auto/tech trades, tools, or hiring/offering artisans. '
                f'Caption: "{text}". Category: "{category}". '
                'Reply strictly with JSON: {"allowed": true/false, "reason": "short reason"}.'
            )
            body = json.dumps({
                'contents': [{'parts': [{'text': prompt}]}],
                'generationConfig': {'temperature': 0.0, 'maxOutputTokens': 80},
            }).encode('utf-8')
            req = urllib.request.Request(
                f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}',
                data=body,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                gdata = json.loads(resp.read().decode('utf-8'))
            reply_txt = gdata['candidates'][0]['content']['parts'][0]['text']
            m = re.search(r'\{.*\}', reply_txt, re.S)
            if m:
                parsed = json.loads(m.group(0))
                if 'allowed' in parsed:
                    is_violation = not bool(parsed['allowed'])
        except Exception:
            pass

    if not is_violation:
        return None

    reason = (
        'Off-topic / non-fix content detected. LocalFix only allows photos and videos about real repairs, fixes, installations, and technical trades.'
    )

    if not profile:
        return Response(
            {
                'success': False,
                'moderation_action': 'warning',
                'warning_count': 1,
                'error': f'WARNING: {reason} Your content was NOT published to others.',
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    profile.warning_count += 1
    if profile.warning_count == 1:
        action = 'warning'
        profile.save(update_fields=['warning_count', 'updated_at'])
        ContentModerationLog.objects.create(
            user_email=profile.email,
            content_type=content_type,
            caption=text[:300],
            reason=reason,
            action_taken=action,
        )
        return Response(
            {
                'success': False,
                'moderation_action': 'warning',
                'warning_count': 1,
                'error': (
                    'WARNING (Strike 1 of 2): Only repair, fix, and trade photos/videos are allowed on LocalFix. '
                    'Your post was blocked and will NOT appear to others. Posting non-fix content again will lock your account for 7 days (and 30 days on repeat offense).'
                ),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if profile.warning_count == 2:
        lock_days = 7
        action = 'locked_7_days'
        profile.lock_reason = 'Second non-fix content violation (7-day lock)'
    else:
        lock_days = 30
        action = 'locked_30_days'
        profile.lock_reason = 'Repeated non-fix content violation (30-day / 1-month lock)'

    profile.locked_until = now + timedelta(days=lock_days)
    profile.save(update_fields=['warning_count', 'locked_until', 'lock_reason', 'updated_at'])
    ContentModerationLog.objects.create(
        user_email=profile.email,
        content_type=content_type,
        caption=text[:300],
        reason=reason,
        action_taken=action,
    )
    unlock_str = profile.locked_until.strftime('%Y-%m-%d %H:%M UTC')
    return Response(
        {
            'success': False,
            'moderation_action': action,
            'warning_count': profile.warning_count,
            'locked_until': profile.locked_until.isoformat(),
            'error': (
                f'ACCOUNT LOCKED FOR {lock_days} DAYS: You uploaded non-fix content after receiving a warning. '
                f'Your post was NOT shown to others and your account is locked until {unlock_str}.'
            ),
        },
        status=status.HTTP_403_FORBIDDEN,
    )


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

    author_email = (request.data.get('author_email') or '').strip().lower()
    caption_text = (request.data.get('text') or '').strip()
    badge_cat = (request.data.get('badge_title') or '').strip()
    mod_block = _moderate_fixes_only_content(author_email, caption_text, 'feed_post', category=badge_cat)
    if mod_block is not None:
        return mod_block

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

    creator_email = (request.data.get('creator_email') or '').strip().lower()
    reel_text = f"{request.data.get('title') or ''} {request.data.get('caption') or ''}".strip()
    reel_cat = (request.data.get('trade_tag') or '').strip()
    mod_block = _moderate_fixes_only_content(creator_email, reel_text, 'video_reel', category=reel_cat)
    if mod_block is not None:
        return mod_block

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
        # Mark messages sent by u2 to u1 (viewer) as read when opening the chat!
        if u1 != u2:
            ChatMessage.objects.filter(
                sender_email__iexact=u2,
                receiver_email__iexact=u1,
                is_read=False,
            ).update(is_read=True)
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
        is_read=(sender_email == receiver_email),
    )
    return Response({'success': True, 'message': ChatMessageSerializer(msg).data}, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
def chat_message_delete_view(request, msg_id):
    requester = (request.query_params.get('email') or request.headers.get('X-User-Email') or '').strip().lower()
    msg = ChatMessage.objects.filter(id=msg_id).first()
    if not msg:
        return Response({'success': False, 'error': 'Message not found.'}, status=status.HTTP_404_NOT_FOUND)
    if requester and msg.sender_email.lower() != requester:
        return Response({'success': False, 'error': 'You can only delete your own messages.'}, status=status.HTTP_403_FORBIDDEN)
    msg.delete()
    return Response({'success': True})


@api_view(['GET'])
def chat_unread_count_view(request):
    my_email = (request.query_params.get('email') or '').strip().lower()
    if not my_email:
        return Response({'success': True, 'unread_count': 0})
    unread = ChatMessage.objects.filter(
        receiver_email__iexact=my_email,
        is_read=False,
    ).exclude(sender_email__iexact=my_email).count()
    return Response({'success': True, 'unread_count': unread})


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

    mod_block = _moderate_fixes_only_content(author_email, caption, 'story')
    if mod_block is not None:
        return mod_block

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
    viewer_email = (request.data.get('viewer_email') or '').strip().lower()
    viewer_name = (request.data.get('viewer_name') or '').strip()
    viewer_avatar = (request.data.get('viewer_avatar') or '').strip()

    if viewer_email and viewer_email != (story.author_email or '').lower():
        prof = UserProfile.objects.filter(email__iexact=viewer_email).first()
        StoryView.objects.update_or_create(
            story=story,
            viewer_email=viewer_email,
            defaults={
                'viewer_name': prof.name if prof else (viewer_name or viewer_email.split('@')[0]),
                'viewer_avatar': (prof.avatar_url if prof and prof.avatar_url else viewer_avatar),
            },
        )
        story.views_count = StoryView.objects.filter(story=story).count()
        story.save(update_fields=['views_count'])
    elif not viewer_email:
        story.views_count += 1
        story.save(update_fields=['views_count'])
    return Response({'success': True, 'views_count': story.views_count})


@api_view(['GET'])
def story_viewers_view(request, story_id):
    story = UserStory.objects.filter(id=story_id).first()
    if not story:
        return Response({'success': False, 'error': 'Story not found.'}, status=status.HTTP_404_NOT_FOUND)
    views = StoryView.objects.filter(story=story).order_by('-viewed_at')
    data = [
        {
            'email': v.viewer_email,
            'name': v.viewer_name,
            'avatar': v.viewer_avatar,
            'viewed_at': v.viewed_at.isoformat(),
        }
        for v in views
    ]
    return Response({'success': True, 'count': len(data), 'viewers': data})


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


# ---- LOCALFIX AI ASSISTANT (CLIENT & ARTISAN EXPERT CONCIERGE) ----

@api_view(['POST'])
def localfix_ai_ask_view(request):
    question = (request.data.get('question') or '').strip()
    role = (request.data.get('role') or 'Customer').strip()
    city = (request.data.get('city') or 'your area').strip()
    currency = (request.data.get('currency') or 'USD').strip().upper()
    user_name = (request.data.get('user_name') or 'there').strip()

    if not question:
        return Response({'success': False, 'error': 'Please enter a question for LocalFix AI.'}, status=status.HTTP_400_BAD_REQUEST)

    total_pros = UserProfile.objects.filter(role='Artisan').count()
    total_users = UserProfile.objects.count()
    total_posts = FeedPost.objects.count()

    # 1. If GEMINI_API_KEY is configured on Render, answer with live Gemini 2.0 Flash grounded in LocalFix rules!
    gemini_key = os.environ.get('GEMINI_API_KEY', '').strip()
    if gemini_key:
        system_context = (
            'You are LocalFix AI, the official built-in assistant inside the LocalFix mobile app for both Clients/Employers and Artisans/Technicians. '
            f'User: {user_name}, Role: {role}, Location: {city}, Currency: {currency}. '
            f'Live platform stats: {total_pros} registered artisans, {total_users} total members, {total_posts} live fix posts. '
            'Key LocalFix features you must explain accurately: '
            '1) Escrow Custody Vault protects payments until milestones are approved. '
            '2) Worldwide Live GPS Tracker auto-locks employee/artisan device GPS (no manual spoofing) and lets Employers filter by "My Team" and open exact locations in Google Maps. '
            '3) Fixes-Only Policy: ONLY repair/fix/trade photos & videos are allowed; non-fix posts are blocked, 1st offense gives a warning, 2nd offense locks account for 7 days, 3rd+ offense locks for 30 days. '
            '4) Verification Badge: Only official LocalFix company accounts (gold) and paid Weekly/Monthly/Yearly subscribers via Paystack/Stripe receive the verified badge. '
            '5) Live 2-way WebRTC Audio & Video Calls, Chat Voice Notes, Chat Images, Message Deletion (long-press), 24-Hour Stories with Viewer list (tap eye icon), Follow Pro, and Dark/Light Mode. '
            'Also give practical repair diagnostics, safety tips, and fair price estimates in the user currency. Keep answers clear, friendly, and concise.'
        )
        try:
            body = json.dumps({
                'contents': [{'parts': [{'text': f'{system_context}\n\nUser Question: {question}'}]}],
                'generationConfig': {'temperature': 0.4, 'maxOutputTokens': 500},
            }).encode('utf-8')
            req = urllib.request.Request(
                f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}',
                data=body,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                gdata = json.loads(resp.read().decode('utf-8'))
            answer = gdata['candidates'][0]['content']['parts'][0]['text'].strip()
            if answer:
                return Response({'success': True, 'answer': answer, 'engine': 'gemini'})
        except Exception:
            pass

    # 2. Built-in Comprehensive LocalFix Expert AI Engine (works 100% 24/7 with zero external API keys!)
    q = question.lower()
    if any(w in q for w in ('lock', 'ban', 'warning', 'block', 'policy', 'post rejected', 'non-fix', 'not about fix')):
        answer = (
            "🛡️ **LocalFix Fixes-Only Policy & Account Locks:**\n"
            "• Only photos, videos, and stories showing **real repairs, fixes, installations, tools, or trade jobs** are allowed.\n"
            "• Off-topic posts (memes, selfies, dancing, spam, etc.) are automatically blocked and **never shown to other users**.\n"
            "• **Strike 1**: You receive a clear warning before any lock.\n"
            "• **Strike 2**: Your account is locked for **7 days**.\n"
            "• **Strike 3+**: Your account is locked for **30 days (1 month)**.\n\n"
            "Tip: Include clear repair details in your caption (e.g., *\"Solar inverter installation & wiring fix\"* or *\"Replaced leaking kitchen pipe\"*)."
        )
    elif any(w in q for w in ('badge', 'verify', 'verified', 'premium', 'pay', 'subscription', 'paystack', 'stripe')):
        answer = (
            "✅ **How LocalFix Verification Badges Work:**\n"
            "• **Gold Badge**: Reserved exclusively for Official LocalFix Company accounts.\n"
            "• **Purple Premium Badge**: Available to verified Artisans & Employers through real payment checkout (**Weekly — 7 days**, **Monthly — 30 days**, or **Yearly — 365 days**).\n"
            "• Go to **Menu → Profile → Get Verified Badge**, choose your plan, complete real payment, and tap **Verify Payment**—your badge activates automatically and expires at the end of your paid period."
        )
    elif any(w in q for w in ('gps', 'location', 'track', 'team', 'employee', 'employer', 'map', 'where')):
        answer = (
            f"📍 **Worldwide Live GPS & Employer's \"My Team\" ({total_pros} artisans registered):**\n"
            "• Employees cannot type or fake their location—LocalFix asks the device to turn on GPS and automatically captures exact latitude, longitude, and street address.\n"
            "• As an Employer, tap **+ Add to My Team** on any employee's post or GPS card, then open the **Nearby / GPS** tab and switch to **My Team**.\n"
            "• Tap any employee to zoom straight to their exact street anywhere in the world or tap **Google Maps** for live directions."
        )
    elif any(w in q for w in ('escrow', 'safe', 'money', 'scam', 'refund', 'dispute', 'milestone')):
        answer = (
            "🔐 **How LocalFix Escrow Protects Both Clients & Artisans:**\n"
            "• **For Clients**: Your payment stays safely locked in Escrow custody until the artisan completes the agreed repair milestone and you approve release.\n"
            "• **For Artisans**: You can start work with confidence knowing the client's funds are already secured before you buy parts or travel to the site.\n"
            "• Open the **Escrow** tab anytime to track active milestones, authorize release, or raise a dispute."
        )
    elif any(w in q for w in ('call', 'voice', 'audio', 'video call', 'chat', 'delete message', 'voice note')):
        answer = (
            "📞 **Chat, Voice Notes, Images & Live 2-Way Calls:**\n"
            "• **Send Photos & Voice Notes**: Inside any chat (including **Saved Messages** to yourself), tap the **Camera** icon for images or the **Mic** icon to record a voice note.\n"
            "• **Delete a Message**: Long-press any message you sent and tap **Delete Message**.\n"
            "• **Live Calls**: Tap the **Phone** or **Video** icon at the top of a chat to start an encrypted live WebRTC call anywhere in the world."
        )
    elif any(w in q for w in ('story', 'stories', 'status', 'eye', 'viewer', '24')):
        answer = (
            "✨ **24-Hour Work & Job Stories:**\n"
            "• Tap **Add 24h Story** at the top of Home Feed to share a repair photo, video clip, or availability status—it auto-expires after 24 hours.\n"
            "• Open your story and tap the **Eye icon (👁 views)** to see the exact list of real users who viewed your story."
        )
    elif any(w in q for w in ('solar', 'inverter', 'electric', 'wiring', 'breaker', 'light', 'socket', 'power')):
        answer = (
            f"⚡ **Electrical & Solar Fix Guide ({city}):**\n"
            "• **Safety First**: Always switch off the main breaker before inspecting sockets, panels, or inverter terminals.\n"
            "• **Common Checks**: Tripping breakers usually indicate an overloaded circuit or short; inverter low-backup often means sulfated batteries or loose DC lugs.\n"
            "• **Typical Service Range**: Diagnostic/socket fix ~\$25–\$65 (or equivalent in local currency); full inverter/solar installation varies by kVA.\n"
            "• **Next Step**: Post a photo/video of the fault on Home Feed or open **Nearby / GPS** to call a nearby Electrical & Solar pro!"
        )
    elif any(w in q for w in ('plumb', 'pipe', 'leak', 'water', 'toilet', 'sink', 'tap', 'drain', 'pump')):
        answer = (
            f"🔧 **Plumbing & Leak Repair Guide ({city}):**\n"
            "• **Immediate Step**: Shut off the nearest isolation valve or main water supply to prevent water damage.\n"
            "• **Common Causes**: Worn rubber washers/cartridges (dripping taps), loose P-trap seals (under-sink leaks), or grease/hair buildup (slow drains).\n"
            "• **Typical Service Range**: Leak/tap fix ~\$20–\$55; pipe replacement or water pump repair ~\$50–\$140.\n"
            "• Tap **Nearby / GPS** to find and chat with a real plumber right now!"
        )
    elif any(w in q for w in ('ac', 'hvac', 'aircon', 'cooling', 'fridge', 'freezer', 'compressor')):
        answer = (
            f"❄️ **AC / HVAC & Cooling Troubleshooting ({city}):**\n"
            "• **Not Cooling**: Check if the indoor air filter is clogged with dust, verify thermostat mode is on *Cool*, and listen for whether the outdoor compressor/fan is spinning.\n"
            "• **Water Dripping Inside**: Usually a blocked condensate drain pipe—needs flushing.\n"
            "• **Typical Service Range**: AC servicing & coil wash ~\$25–\$60; refrigerant gas refill or capacitor replacement ~\$45–\$120.\n"
            "• Hire a certified HVAC artisan via **Nearby / GPS** and protect payment with **Escrow**!"
        )
    elif any(w in q for w in ('car', 'auto', 'mechanic', 'engine', 'brake', 'battery', 'generator', 'gen')):
        answer = (
            f"🚗 **Auto & Generator Repair Guide ({city}):**\n"
            "• **Won't Start**: Check battery voltage/terminals, fuel supply, spark plug, and oil level sensor.\n"
            "• **Overheating / Smoke**: Stop running immediately to avoid engine damage—check coolant, radiator fan, or oil level.\n"
            "• **Pro Tip**: Upload a 10-second video of the sound/engine on LocalFix Home Feed so mechanics can diagnose it and send you a quote!"
        )
    elif role.lower() == 'artisan':
        answer = (
            f"👋 Hi {user_name}! As a **LocalFix Artisan**, here's how to win more jobs in {city}:\n"
            "1. **Upload Your Real Profile Photo** in Profile so employers recognize and trust you.\n"
            "2. **Keep Device GPS ON** so nearby employers & clients can find you on the live map.\n"
            "3. **Post Real Repair Videos & 24h Work Stories** (fixes-only!) so clients see your skills and **Follow** you.\n"
            "4. **Get Verified** (Weekly/Monthly/Yearly) to stand out with the Verified Badge.\n\n"
            "Ask me anything about pricing jobs, Escrow milestones, troubleshooting a repair, or using any LocalFix feature!"
        )
    else:
        answer = (
            f"👋 Hi {user_name}! I'm **LocalFix AI**—here to help both Clients and Artisans in {city} ({total_pros} registered pros, {total_posts} live fix posts).\n\n"
            "You can ask me:\n"
            "• **Repair help & cost estimates** (Electrical, Solar, Plumbing, AC/HVAC, Auto, Generators, Carpentry)\n"
            "• **How to hire safely with Escrow Custody**\n"
            "• **How Employer \"My Team\" & Worldwide GPS Tracking work**\n"
            "• **Verification Badges, 24h Stories, Voice Notes, Live Calls, or Fixes-Only Policy**\n\n"
            "What repair or LocalFix question can I help you with right now?"
        )

    return Response({'success': True, 'answer': answer, 'engine': 'localfix_expert_ai'})
