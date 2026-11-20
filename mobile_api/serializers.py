from rest_framework import serializers
from .models import (
    UserProfile,
    FeedPost,
    PostComment,
    VideoReel,
    ReelComment,
    ChatMessage,
    NearbyArtisan,
    EscrowContract,
)


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        exclude = ['password_hash']


class PostCommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostComment
        fields = '__all__'


class FeedPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedPost
        fields = '__all__'


class ReelCommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReelComment
        fields = '__all__'


class VideoReelSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoReel
        fields = '__all__'


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = '__all__'


class NearbyArtisanSerializer(serializers.ModelSerializer):
    class Meta:
        model = NearbyArtisan
        fields = '__all__'


class EscrowContractSerializer(serializers.ModelSerializer):
    class Meta:
        model = EscrowContract
        fields = '__all__'
