from django.db import models


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('Customer', 'Customer'),
        ('Artisan', 'Artisan'),
    ]

    name = models.CharField(max_length=120, default='LocalFix User')
    handle = models.CharField(max_length=60, blank=True, default='')
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=256, blank=True, default='')
    auth_provider = models.CharField(max_length=20, default='email')
    google_id = models.CharField(max_length=128, blank=True, default='')
    phone = models.CharField(max_length=32, blank=True, default='')
    bio = models.TextField(
        blank=True,
        default='Connecting with verified global artisans for home, solar, and smart repair projects.',
    )
    trade = models.CharField(max_length=120, blank=True, default='Verified Member')
    city = models.CharField(max_length=160, blank=True, default='')
    exact_address = models.TextField(blank=True, default='')
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    gps_accuracy = models.FloatField(null=True, blank=True)
    location_updated_at = models.DateTimeField(null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='Customer')
    avatar_url = models.TextField(blank=True, default='')
    country_code = models.CharField(max_length=8, default='US')
    currency_code = models.CharField(max_length=8, default='USD')
    language = models.CharField(max_length=40, default='English (Global)')
    is_dark_mode = models.BooleanField(default=False)
    is_company_verified = models.BooleanField(default=False)
    verified_plan = models.CharField(max_length=20, blank=True, default='')
    verified_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.name} <{self.email}> ({self.role})'


class LocationLog(models.Model):
    user = models.ForeignKey(UserProfile, related_name='location_logs', on_delete=models.CASCADE)
    email = models.EmailField(db_index=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    exact_address = models.TextField(blank=True, default='')
    city = models.CharField(max_length=160, blank=True, default='')
    country_code = models.CharField(max_length=8, blank=True, default='')
    accuracy = models.FloatField(null=True, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-recorded_at']


class StoredMedia(models.Model):
    uuid_key = models.CharField(max_length=64, unique=True, db_index=True)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120, default='application/octet-stream')
    data = models.BinaryField()
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.uuid_key}/{self.filename} ({self.size} bytes)'


class FeedPost(models.Model):
    author_name = models.CharField(max_length=120)
    author_email = models.EmailField(blank=True, default='')
    author_avatar = models.TextField(blank=True, default='')
    badge_title = models.CharField(max_length=120, default='Verified Member')
    location = models.CharField(max_length=120, default='Global')
    text = models.TextField()
    image_url = models.TextField(blank=True, default='')
    video_url = models.TextField(blank=True, default='')
    is_video = models.BooleanField(default=False)
    escrow_usd = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    likes = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)
    shares_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.author_name}: {self.text[:40]}'


class PostLike(models.Model):
    post = models.ForeignKey(FeedPost, related_name='like_records', on_delete=models.CASCADE)
    user_email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('post', 'user_email')


class PostComment(models.Model):
    post = models.ForeignKey(FeedPost, related_name='comments', on_delete=models.CASCADE)
    parent = models.ForeignKey('self', null=True, blank=True, related_name='replies', on_delete=models.CASCADE)
    author_name = models.CharField(max_length=120)
    author_email = models.EmailField(blank=True, default='')
    author_avatar = models.TextField(blank=True, default='')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class VideoReel(models.Model):
    creator_name = models.CharField(max_length=120)
    creator_email = models.EmailField(blank=True, default='')
    creator_avatar = models.TextField(blank=True, default='')
    trade_tag = models.CharField(max_length=60, default='VERIFIED PRO')
    title = models.CharField(max_length=160)
    caption = models.TextField(blank=True)
    thumbnail_url = models.TextField(blank=True, default='')
    video_url = models.TextField(blank=True, default='')
    location = models.CharField(max_length=120, blank=True, default='Global')
    price_usd = models.DecimalField(max_digits=10, decimal_places=2, default=45)
    direct_booking_enabled = models.BooleanField(default=True)
    escrow_protected = models.BooleanField(default=True)
    likes = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)
    shares_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} by {self.creator_name}'


class ReelLike(models.Model):
    reel = models.ForeignKey(VideoReel, related_name='like_records', on_delete=models.CASCADE)
    user_email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('reel', 'user_email')


class ReelComment(models.Model):
    reel = models.ForeignKey(VideoReel, related_name='comments', on_delete=models.CASCADE)
    parent = models.ForeignKey('self', null=True, blank=True, related_name='replies', on_delete=models.CASCADE)
    author_name = models.CharField(max_length=120)
    author_email = models.EmailField(blank=True, default='')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class ChatMessage(models.Model):
    sender_email = models.EmailField()
    sender_name = models.CharField(max_length=120)
    receiver_email = models.EmailField()
    receiver_name = models.CharField(max_length=120)
    text = models.TextField(blank=True, default='')
    message_type = models.CharField(max_length=20, default='text')  # text, image, voice
    media_url = models.TextField(blank=True, default='')
    audio_duration_sec = models.PositiveIntegerField(default=0)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class NearbyArtisan(models.Model):
    name = models.CharField(max_length=120)
    profession = models.CharField(max_length=120)
    city = models.CharField(max_length=120)
    distance_km = models.FloatField(default=1.0)
    eta_minutes = models.PositiveIntegerField(default=10)
    rating = models.FloatField(default=4.9)
    hourly_rate_usd = models.DecimalField(max_digits=10, decimal_places=2, default=40)
    avatar_url = models.URLField(blank=True)
    is_online = models.BooleanField(default=True)


class EscrowContract(models.Model):
    title = models.CharField(max_length=160)
    artisan_name = models.CharField(max_length=120)
    amount_usd = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=40, default='In Escrow Custody')
    created_at = models.DateTimeField(auto_now_add=True)


class CallSession(models.Model):
    STATUS_CHOICES = [
        ('ringing', 'Ringing'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('ended', 'Ended'),
    ]

    caller_email = models.EmailField(db_index=True)
    caller_name = models.CharField(max_length=120)
    caller_avatar = models.TextField(blank=True, default='')
    callee_email = models.EmailField(db_index=True)
    callee_name = models.CharField(max_length=120)
    callee_avatar = models.TextField(blank=True, default='')
    is_video = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ringing')
    offer_sdp = models.TextField(blank=True, default='')
    answer_sdp = models.TextField(blank=True, default='')
    caller_candidates = models.TextField(blank=True, default='[]')
    callee_candidates = models.TextField(blank=True, default='[]')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class UserStory(models.Model):
    author_email = models.EmailField(db_index=True)
    author_name = models.CharField(max_length=120)
    author_avatar = models.TextField(blank=True, default='')
    author_role = models.CharField(max_length=40, default='Member')
    media_url = models.TextField(blank=True, default='')
    is_video = models.BooleanField(default=False)
    caption = models.TextField(blank=True, default='')
    location = models.CharField(max_length=160, blank=True, default='')
    views_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ['-created_at']


class UserFollow(models.Model):
    follower_email = models.EmailField(db_index=True)
    following_email = models.EmailField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('follower_email', 'following_email')


class TeamMember(models.Model):
    employer_email = models.EmailField(db_index=True)
    employee_email = models.EmailField(db_index=True)
    label = models.CharField(max_length=80, blank=True, default='Team Employee')
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('employer_email', 'employee_email')
        ordering = ['-added_at']
