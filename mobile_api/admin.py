from django.contrib import admin
from .models import (
    UserProfile,
    FeedPost,
    PostLike,
    PostComment,
    VideoReel,
    ReelLike,
    ReelComment,
    ChatMessage,
    NearbyArtisan,
    EscrowContract,
)

admin.site.register(UserProfile)
admin.site.register(FeedPost)
admin.site.register(PostLike)
admin.site.register(PostComment)
admin.site.register(VideoReel)
admin.site.register(ReelLike)
admin.site.register(ReelComment)
admin.site.register(ChatMessage)
admin.site.register(NearbyArtisan)
admin.site.register(EscrowContract)
