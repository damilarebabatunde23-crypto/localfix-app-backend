from django.contrib import admin
from .models import UserProfile, FeedPost, VideoReel, NearbyArtisan, EscrowContract

admin.site.register(UserProfile)
admin.site.register(FeedPost)
admin.site.register(VideoReel)
admin.site.register(NearbyArtisan)
admin.site.register(EscrowContract)
