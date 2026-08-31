from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    ROLE_CHOICES = (
        ('artisan', 'Artisan'),
        ('buyer', 'Buyer'),
        ('admin', 'Admin'),
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    phone = models.CharField(max_length=15, unique=True)
    region = models.CharField(max_length=100, default='')
    preferred_language = models.CharField(max_length=20, default='en')

    class Meta:
        db_table = 'users'

    def __str__(self):
        return f"{self.username} ({self.role})"


class ArtisanProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='artisan_profile',
        db_column='user_id'
    )
    craft_type = models.CharField(max_length=100, default='')
    bio = models.TextField(null=True, blank=True)
    verified = models.BooleanField(default=False)

    class Meta:
        db_table = 'artisan_profiles'

    def __str__(self):
        return f"Artisan: {self.user.username}"


class BuyerProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='buyer_profile',
        db_column='user_id'
    )
    # The DB table uses a default_shipping_address_id FK to the addresses table.
    # Address management is handled separately; no text field here.

    class Meta:
        db_table = 'buyer_profiles'
        managed = False  # Don't let Django try to create/alter this table

    def __str__(self):
        return f"Buyer: {self.user.username}"
