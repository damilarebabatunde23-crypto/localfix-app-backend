from django.urls import path
from . import views

urlpatterns = [
    path('health/', views.health_check, name='mobile-health'),
    path('location/ip/', views.location_from_ip, name='mobile-ip-location'),
    path('location/update/', views.update_gps_location_view, name='mobile-gps-update'),
    path('location/history/', views.location_history_view, name='mobile-gps-history'),
    path('auth/login/', views.auth_login, name='mobile-login'),
    path('auth/register/', views.auth_register, name='mobile-register'),
    path('auth/google/', views.auth_google, name='mobile-google-auth'),
    path('users/', views.users_list_view, name='mobile-users'),
    path('profile/', views.profile_view, name='mobile-profile'),
    path('media/upload/', views.media_upload_view, name='mobile-media-upload'),
    path('feed/', views.feed_view, name='mobile-feed'),
    path('feed/<int:post_id>/like/', views.feed_toggle_like, name='mobile-feed-like'),
    path('feed/<int:post_id>/comments/', views.feed_comments_view, name='mobile-feed-comments'),
    path('reels/', views.reels_view, name='mobile-reels'),
    path('reels/<int:reel_id>/like/', views.reel_toggle_like, name='mobile-reel-like'),
    path('reels/<int:reel_id>/comments/', views.reel_comments_view, name='mobile-reel-comments'),
    path('chat/conversations/', views.chat_conversations_view, name='mobile-chat-conversations'),
    path('chat/messages/', views.chat_messages_view, name='mobile-chat-messages'),
    path('artisans/nearby/', views.nearby_artisans_view, name='mobile-nearby-artisans'),
    path('escrow/', views.escrow_summary_view, name='mobile-escrow'),
]
