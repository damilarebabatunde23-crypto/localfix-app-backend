from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, include


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
            'profile': '/api/profile/',
            'feed': '/api/feed/',
            'reels': '/api/reels/',
            'nearby_artisans': '/api/artisans/nearby/?radiusKm=15',
            'escrow': '/api/escrow/',
            'admin': '/admin/',
        },
    })


urlpatterns = [
    path('', api_root, name='api-root'),
    path('admin/', admin.site.urls),
    path('api/', include('mobile_api.urls')),
]
