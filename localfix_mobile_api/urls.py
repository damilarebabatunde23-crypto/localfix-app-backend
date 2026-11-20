from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, include, re_path
from django.views.static import serve


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
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]
