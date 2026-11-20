import json
import os
import secrets
import urllib.request
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import UserProfile, FeedPost, VideoReel, NearbyArtisan, EscrowContract
from .serializers import (
    UserProfileSerializer,
    FeedPostSerializer,
    VideoReelSerializer,
    NearbyArtisanSerializer,
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
        {
            'success': True,
            'token': token,
            'user': UserProfileSerializer(profile).data,
        },
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
    return Response({
        'success': True,
        'token': token,
        'user': UserProfileSerializer(profile).data,
    })


@api_view(['POST'])
def auth_google(request):
    id_token = (request.data.get('id_token') or '').strip()
    role = (request.data.get('role') or 'Customer').strip()
    city = (request.data.get('city') or '').strip()
    country_code = (request.data.get('country_code') or 'US').strip().upper()

    if not id_token:
        return Response(
            {'success': False, 'error': 'Missing Google id_token.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        verify_url = f'https://oauth2.googleapis.com/tokeninfo?id_token={id_token}'
        with urllib.request.urlopen(verify_url, timeout=8) as resp:
            info = json.loads(resp.read().decode('utf-8'))
    except Exception:
        return Response(
            {'success': False, 'error': 'Invalid or expired Google token.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

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

    profile, _ = UserProfile.objects.update_or_create(
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
        },
    )
    token = f'lf_g_{secrets.token_urlsafe(32)}'
    return Response({
        'success': True,
        'token': token,
        'user': UserProfileSerializer(profile).data,
    })


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

    serializer = UserProfileSerializer(profile, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response({'success': True, 'profile': serializer.data})
    return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'POST'])
def feed_view(request):
    if request.method == 'GET':
        posts = FeedPost.objects.all()
        return Response({'success': True, 'posts': FeedPostSerializer(posts, many=True).data})

    serializer = FeedPostSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({'success': True, 'post': serializer.data}, status=status.HTTP_201_CREATED)
    return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'POST'])
def reels_view(request):
    if request.method == 'GET':
        reels = VideoReel.objects.all()
        return Response({'success': True, 'reels': VideoReelSerializer(reels, many=True).data})

    serializer = VideoReelSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({'success': True, 'reel': serializer.data}, status=status.HTTP_201_CREATED)
    return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
def nearby_artisans_view(request):
    radius_km = float(request.query_params.get('radiusKm', 50))
    city = request.query_params.get('city')
    qs = NearbyArtisan.objects.filter(distance_km__lte=radius_km)
    if city:
        qs = qs.filter(city__icontains=city)
    return Response({
        'success': True,
        'count': qs.count(),
        'artisans': NearbyArtisanSerializer(qs, many=True).data,
    })


@api_view(['GET'])
def escrow_summary_view(request):
    contracts = EscrowContract.objects.all()
    total = sum(float(c.amount_usd) for c in contracts)
    return Response({
        'success': True,
        'vault_balance_usd': total or 1240.0,
        'active_contracts': contracts.count(),
        'contracts': EscrowContractSerializer(contracts, many=True).data,
    })
