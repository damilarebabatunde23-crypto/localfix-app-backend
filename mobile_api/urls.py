from django.urls import path
from . import views

urlpatterns = [
    path('health/', views.health_check, name='mobile-health'),
    path('auth/login/', views.auth_login, name='mobile-login'),
    path('auth/register/', views.auth_register, name='mobile-register'),
    path('profile/', views.profile_view, name='mobile-profile'),
    path('feed/', views.feed_view, name='mobile-feed'),
    path('reels/', views.reels_view, name='mobile-reels'),
    path('artisans/nearby/', views.nearby_artisans_view, name='mobile-nearby-artisans'),
    path('escrow/', views.escrow_summary_view, name='mobile-escrow'),
]
