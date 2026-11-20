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


def _get_or_create_default_profile():
    profile, _ = UserProfile.objects.get_or_create(
        email='user@localfix.com',
        defaults={
            'name': 'Damilare Babatunde',
            'handle': '@damilare_fix',
            'role': 'Customer',
        },
    )
    return profile


@api_view(['GET'])
def health_check(request):
    return Response({
        'status': 'ok',
        'framework': 'Django REST Framework',
        'service': 'localfix-mobile-backend',
        'timestamp': timezone.now().isoformat(),
    })


@api_view(['POST'])
def auth_login(request):
    email = request.data.get('email') or 'user@localfix.com'
    role = request.data.get('role') or 'Customer'
    profile, _ = UserProfile.objects.get_or_create(
        email=email,
        defaults={'name': request.data.get('name', 'LocalFix User'), 'role': role},
    )
    return Response({
        'success': True,
        'token': 'django_jwt_session_token',
        'user': UserProfileSerializer(profile).data,
    })


@api_view(['POST'])
def auth_register(request):
    email = request.data.get('email') or 'newuser@localfix.com'
    profile, _ = UserProfile.objects.update_or_create(
        email=email,
        defaults={
            'name': request.data.get('name', 'New Member'),
            'role': request.data.get('role', 'Customer'),
        },
    )
    return Response(
        {
            'success': True,
            'token': 'django_jwt_session_token',
            'user': UserProfileSerializer(profile).data,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'PUT', 'PATCH'])
def profile_view(request):
    profile = _get_or_create_default_profile()
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

    data = request.data.copy()
    profile = _get_or_create_default_profile()
    data.setdefault('creator_name', profile.name)
    serializer = VideoReelSerializer(data=data)
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
