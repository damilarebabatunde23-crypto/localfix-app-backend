from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

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
    NearbyArtisan,
    EscrowContract,
    CallSession,
    UserStory,
    StoryView,
    UserFollow,
    TeamMember,
    PaymentTransaction,
    ContentModerationLog,
    Notification,
)

# Brand Django Admin for LocalFix
admin.site.site_header = 'LocalFix Command Admin'
admin.site.site_title = 'LocalFix Backend Admin'
admin.site.index_title = 'Global Platform Management & Moderation'
admin.site.site_url = '/'


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'email',
        'role_pill',
        'city',
        'verified_status',
        'moderation_status',
        'auth_provider',
        'location_updated_at',
    )
    list_filter = ('role', 'is_company_verified', 'verified_plan', 'auth_provider', 'country_code')
    search_fields = ('name', 'email', 'handle', 'trade', 'city', 'exact_address', 'phone')
    readonly_fields = ('created_at', 'updated_at', 'location_updated_at')
    actions = ('grant_company_verified', 'revoke_verified_badge', 'unlock_accounts')

    @admin.display(description='Role', ordering='role')
    def role_pill(self, obj):
        if (obj.role or '').lower() == 'artisan':
            return mark_safe(
                '<span style="display:inline-block;padding:2px 9px;border-radius:999px;font-weight:700;font-size:11px;background:#5B13EC;color:#FFFFFF;">Artisan Pro</span>'
            )
        return mark_safe(
            '<span style="display:inline-block;padding:2px 9px;border-radius:999px;font-weight:700;font-size:11px;background:#0EA5E9;color:#FFFFFF;">Client</span>'
        )

    @admin.display(description='Verification')
    def verified_status(self, obj):
        now = timezone.now()
        if obj.is_company_verified:
            return mark_safe(
                '<span style="color:#10B981;font-weight:700;">✔ Company Verified</span>'
            )
        if obj.verified_until and obj.verified_until > now:
            return format_html(
                '<span style="color:#7C3AED;font-weight:700;">★ Paid ({})</span>',
                obj.verified_plan or 'active',
            )
        return mark_safe('<span style="opacity:0.6;">Standard</span>')

    @admin.display(description='Account Safety')
    def moderation_status(self, obj):
        now = timezone.now()
        if obj.locked_until and obj.locked_until > now:
            return format_html(
                '<span style="color:#EF4444;font-weight:700;">🔒 Locked until {}</span>',
                obj.locked_until.strftime('%Y-%m-%d %H:%M'),
            )
        if obj.warning_count > 0:
            return format_html(
                '<span style="color:#F59E0B;font-weight:700;">⚠ {} warning(s)</span>',
                obj.warning_count,
            )
        return mark_safe('<span style="color:#10B981;">Clear</span>')

    @admin.action(description='Grant Official Company Verified Badge')
    def grant_company_verified(self, request, queryset):
        updated = queryset.update(is_company_verified=True, verified_plan='company')
        self.message_user(request, f'Granted Company Verified Badge to {updated} user(s).')

    @admin.action(description='Revoke Verified Badge')
    def revoke_verified_badge(self, request, queryset):
        updated = queryset.update(is_company_verified=False, verified_plan='', verified_until=None)
        self.message_user(request, f'Revoked Verified Badge for {updated} user(s).')

    @admin.action(description='Unlock Selected Accounts & Reset Warnings')
    def unlock_accounts(self, request, queryset):
        updated = queryset.update(locked_until=None, lock_reason='', warning_count=0)
        self.message_user(request, f'Unlocked and reset warnings for {updated} user(s).')


@admin.register(LocationLog)
class LocationLogAdmin(admin.ModelAdmin):
    list_display = ('email', 'city', 'country_code', 'latitude', 'longitude', 'accuracy', 'recorded_at')
    list_filter = ('country_code',)
    search_fields = ('email', 'city', 'exact_address')
    readonly_fields = ('recorded_at',)


@admin.register(StoredMedia)
class StoredMediaAdmin(admin.ModelAdmin):
    list_display = ('uuid_key', 'filename', 'content_type', 'formatted_size', 'created_at')
    list_filter = ('content_type',)
    search_fields = ('uuid_key', 'filename', 'content_type')
    exclude = ('data',)
    readonly_fields = ('uuid_key', 'size', 'created_at')

    @admin.display(description='Size', ordering='size')
    def formatted_size(self, obj):
        if obj.size >= 1024 * 1024:
            return f'{obj.size / (1024 * 1024):.2f} MB'
        if obj.size >= 1024:
            return f'{obj.size / 1024:.1f} KB'
        return f'{obj.size} B'


@admin.register(FeedPost)
class FeedPostAdmin(admin.ModelAdmin):
    list_display = ('author_name', 'author_email', 'short_text', 'location', 'is_video', 'likes', 'comments_count', 'created_at')
    list_filter = ('is_video', 'created_at')
    search_fields = ('author_name', 'author_email', 'text', 'location')
    readonly_fields = ('created_at',)

    @admin.display(description='Caption')
    def short_text(self, obj):
        return (obj.text[:65] + '…') if len(obj.text) > 65 else obj.text


@admin.register(PostLike)
class PostLikeAdmin(admin.ModelAdmin):
    list_display = ('post', 'user_email', 'created_at')
    search_fields = ('user_email',)


@admin.register(PostComment)
class PostCommentAdmin(admin.ModelAdmin):
    list_display = ('post', 'author_name', 'author_email', 'parent', 'text', 'created_at')
    search_fields = ('author_name', 'author_email', 'text')


@admin.register(VideoReel)
class VideoReelAdmin(admin.ModelAdmin):
    list_display = ('title', 'creator_name', 'trade_tag', 'location', 'price_usd', 'likes', 'comments_count', 'created_at')
    list_filter = ('trade_tag', 'direct_booking_enabled', 'escrow_protected')
    search_fields = ('title', 'caption', 'creator_name', 'creator_email', 'location')


@admin.register(ReelLike)
class ReelLikeAdmin(admin.ModelAdmin):
    list_display = ('reel', 'user_email', 'created_at')
    search_fields = ('user_email',)


@admin.register(ReelComment)
class ReelCommentAdmin(admin.ModelAdmin):
    list_display = ('reel', 'author_name', 'author_email', 'parent', 'text', 'created_at')
    search_fields = ('author_name', 'author_email', 'text')


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('sender_email', 'receiver_email', 'message_type', 'short_msg', 'is_read', 'created_at')
    list_filter = ('message_type', 'is_read', 'created_at')
    search_fields = ('sender_email', 'receiver_email', 'sender_name', 'receiver_name', 'text')

    @admin.display(description='Message')
    def short_msg(self, obj):
        if obj.message_type == 'voice':
            return f'🎤 Voice ({obj.audio_duration_sec}s)'
        if obj.message_type == 'image':
            return '🖼 Image attachment'
        return (obj.text[:50] + '…') if len(obj.text) > 50 else obj.text


@admin.register(CallSession)
class CallSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'caller_name', 'callee_name', 'is_video', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'is_video')
    search_fields = ('caller_email', 'callee_email', 'caller_name', 'callee_name')


@admin.register(UserStory)
class UserStoryAdmin(admin.ModelAdmin):
    list_display = ('author_name', 'author_role', 'is_video', 'views_count', 'location', 'created_at', 'expires_at')
    list_filter = ('is_video', 'author_role')
    search_fields = ('author_name', 'author_email', 'caption', 'location')


@admin.register(StoryView)
class StoryViewAdmin(admin.ModelAdmin):
    list_display = ('story', 'viewer_name', 'viewer_email', 'viewed_at')
    search_fields = ('viewer_name', 'viewer_email')


@admin.register(UserFollow)
class UserFollowAdmin(admin.ModelAdmin):
    list_display = ('follower_email', 'following_email', 'created_at')
    search_fields = ('follower_email', 'following_email')


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ('employer_email', 'employee_email', 'label', 'added_at')
    search_fields = ('employer_email', 'employee_email', 'label')


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ('reference', 'user_email', 'plan', 'provider', 'currency', 'amount_minor', 'status', 'created_at', 'verified_at')
    list_filter = ('status', 'provider', 'plan', 'currency')
    search_fields = ('reference', 'user_email')


@admin.register(ContentModerationLog)
class ContentModerationLogAdmin(admin.ModelAdmin):
    list_display = ('user_email', 'content_type', 'action_taken', 'reason', 'created_at')
    list_filter = ('action_taken', 'content_type', 'created_at')
    search_fields = ('user_email', 'caption', 'reason')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient_email', 'notif_type', 'title', 'actor_name', 'is_read', 'created_at')
    list_filter = ('notif_type', 'is_read', 'created_at')
    search_fields = ('recipient_email', 'actor_email', 'title', 'body')


@admin.register(NearbyArtisan)
class NearbyArtisanAdmin(admin.ModelAdmin):
    list_display = ('name', 'profession', 'city', 'rating', 'hourly_rate_usd', 'is_online')
    list_filter = ('is_online', 'city')
    search_fields = ('name', 'profession', 'city')


@admin.register(EscrowContract)
class EscrowContractAdmin(admin.ModelAdmin):
    list_display = ('title', 'artisan_name', 'amount_usd', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('title', 'artisan_name')
