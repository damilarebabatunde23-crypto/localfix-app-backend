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
    auth_provider = models.CharField(max_length=20, default='email')  # 'email' or 'google'
    google_id = models.CharField(max_length=128, blank=True, default='')
    phone = models.CharField(max_length=32, blank=True, default='')
    bio = models.TextField(
        blank=True,
        default='Connecting with verified global artisans for home, solar, and smart repair projects.',
    )
    trade = models.CharField(max_length=120, blank=True, default='Verified Member')
    city = models.CharField(max_length=120, blank=True, default='')
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='Customer')
    avatar_url = models.URLField(blank=True, default='')
    country_code = models.CharField(max_length=8, default='US')
    currency_code = models.CharField(max_length=8, default='USD')
    language = models.CharField(max_length=40, default='English (Global)')
    is_dark_mode = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.name} <{self.email}> ({self.role})'


class FeedPost(models.Model):
    author_name = models.CharField(max_length=120)
    badge_title = models.CharField(max_length=120, default='Verified Artisan')
    location = models.CharField(max_length=120, default='Global')
    text = models.TextField()
    image_url = models.URLField(blank=True)
    escrow_usd = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    likes = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)
    shares_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.author_name}: {self.text[:40]}'


class VideoReel(models.Model):
    creator_name = models.CharField(max_length=120)
    trade_tag = models.CharField(max_length=60, default='VERIFIED PRO')
    title = models.CharField(max_length=160)
    caption = models.TextField(blank=True)
    thumbnail_url = models.URLField(blank=True)
    video_url = models.URLField(blank=True)
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

    def __str__(self):
        return f'{self.name} - {self.profession} ({self.city})'


class EscrowContract(models.Model):
    title = models.CharField(max_length=160)
    artisan_name = models.CharField(max_length=120)
    amount_usd = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=40, default='In Escrow Custody')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.title} (${self.amount_usd})'
