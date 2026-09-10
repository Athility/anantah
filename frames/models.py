import os
import logging
from django.db import models
from django.conf import settings
from django.core.files.storage import storages
from django.core.files import File
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from accounts.models import ArtisanProfile, User
from listings.models import Product

logger = logging.getLogger(__name__)


def get_video_storage():
    return storages['video']


def get_image_storage():
    return storages['default']


class Reel(models.Model):
    artisan = models.ForeignKey(
        ArtisanProfile,
        on_delete=models.CASCADE,
        related_name='reels',
        db_column='artisan_id'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reels',
        db_column='product_id'
    )
    video_file = models.FileField(
        upload_to='reels/videos/',
        storage=get_video_storage,
        max_length=255
    )
    thumbnail = models.ImageField(
        upload_to='reels/thumbnails/',
        storage=get_image_storage,
        max_length=255,
        null=True,
        blank=True
    )
    caption = models.CharField(max_length=300, null=True, blank=True)
    view_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'reels'
        ordering = ['-created_at']

    def __str__(self):
        return f"Reel #{self.pk} by {self.artisan}"


class ReelLike(models.Model):
    reel = models.ForeignKey(
        Reel,
        on_delete=models.CASCADE,
        related_name='likes',
        db_column='reel_id'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='reel_likes',
        db_column='user_id'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'reel_likes'
        unique_together = ('reel', 'user')
        ordering = ['-created_at']

    def __str__(self):
        return f"Like by User #{self.user_id} on Reel #{self.reel_id}"


@receiver(post_save, sender=Reel)
def ensure_reel_media_on_cloudinary(sender, instance, **kwargs):
    """
    Post-save signal to ensure video_file and thumbnail are migrated to Cloudinary
    if they were initially saved to local MEDIA_ROOT (matches Product signal pattern).
    """
    if not getattr(settings, 'CLOUDINARY_CONFIGURED', False):
        return

    try:
        video_storage = storages['video']
        image_storage = storages['default']
        updates = {}

        fields_to_check = [
            ('video_file', video_storage),
            ('thumbnail', image_storage),
        ]

        for field_name, target_storage in fields_to_check:
            field = getattr(instance, field_name, None)
            if not field or not field.name:
                continue

            clean_name = field.name.replace('\\', '/')
            lookup_name = clean_name[6:] if clean_name.startswith('media/') else clean_name

            local_path = os.path.join(settings.MEDIA_ROOT, lookup_name)
            alt_path = os.path.join(settings.MEDIA_ROOT, clean_name)

            resolved_path = None
            if os.path.isfile(local_path):
                resolved_path = local_path
            elif os.path.isfile(alt_path):
                resolved_path = alt_path

            if resolved_path:
                try:
                    if not target_storage.exists(clean_name) and not target_storage.exists(lookup_name):
                        with open(resolved_path, 'rb') as f:
                            saved_name = target_storage.save(lookup_name, File(f))
                        updates[field_name] = saved_name
                        logger.info(f"Auto-migrated {field_name} for Reel #{instance.pk} to Cloudinary: {saved_name}")
                except Exception as e:
                    logger.error(f"Failed auto-upload of {field_name} to Cloudinary for Reel #{instance.pk}: {e}")

        if updates:
            Reel.objects.filter(pk=instance.pk).update(**updates)
    except Exception as e:
        logger.error(f"Error in ensure_reel_media_on_cloudinary signal: {e}")


@receiver(post_delete, sender=Reel)
def cleanup_reel_media(sender, instance, **kwargs):
    """
    Clean up video_file and thumbnail from storage upon deletion.
    """
    try:
        if instance.video_file:
            instance.video_file.delete(save=False)
        if instance.thumbnail:
            instance.thumbnail.delete(save=False)
    except Exception as e:
        logger.warning(f"Error deleting media for Reel #{instance.pk}: {e}")
