from django.core.validators import MinValueValidator
from decimal import Decimal
from django.db import models
from django.core.files.storage import storages


def get_audio_storage():
    return storages['audio']


class Category(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        db_table = 'categories'

    def __str__(self):
        return self.name


class Product(models.Model):
    STATUS_CHOICES = (
        ('draft', 'Draft'),
        ('live', 'Live'),
        ('flagged', 'Flagged'),
    )
    artisan = models.ForeignKey(
        'accounts.ArtisanProfile',
        on_delete=models.CASCADE,
        db_column='artisan_id'
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='category_id'
    )
    title_en = models.CharField(max_length=200)
    title_hi = models.CharField(max_length=200, default='')
    description_en = models.TextField(null=True, blank=True)
    description_hi = models.TextField(null=True, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    raw_image = models.ImageField(upload_to='products/raw/', max_length=255)
    refined_image = models.ImageField(upload_to='products/refined/', max_length=255, null=True, blank=True)
    raw_audio = models.FileField(upload_to='products/audio/', storage=get_audio_storage, max_length=255, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'products'

    def __str__(self):
        return self.title_en

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.conf import settings
from django.core.files import File
import os
import logging

logger = logging.getLogger(__name__)

@receiver(post_delete, sender=Product)
def delete_product_files(sender, instance, **kwargs):
    for field in [instance.raw_image, instance.refined_image, instance.raw_audio]:
        if not field or not field.name:
            continue
        try:
            is_local = False
            try:
                if hasattr(field, 'path') and field.path and os.path.isfile(field.path):
                    is_local = True
                    os.remove(field.path)
            except (NotImplementedError, AttributeError, ValueError):
                pass

            if not is_local:
                try:
                    field.storage.delete(field.name)
                except Exception as e:
                    logger.warning(f"Failed to delete remote product file {field.name} from storage: {e}")
        except (OSError, PermissionError) as e:
            logger.warning(f"Failed to delete product file {field.name}: {e}")


@receiver(post_save, sender=Product)
def ensure_media_on_cloudinary(sender, instance, **kwargs):
    """
    Post-save signal to ensure any media file saved to a Product is automatically
    migrated to Cloudinary storage if Cloudinary is configured and the file currently
    resides on local disk.
    """
    if not getattr(settings, 'CLOUDINARY_CONFIGURED', False):
        return

    try:
        from django.core.files.storage import storages
        default_storage = storages['default']
        audio_storage = storages['audio']

        if 'Cloudinary' not in default_storage.__class__.__name__:
            return

        updates = {}
        fields_to_check = [
            ('raw_image', default_storage),
            ('refined_image', default_storage),
            ('raw_audio', audio_storage),
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
                        logger.info(f"Auto-migrated {field_name} for Product #{instance.pk} to Cloudinary: {saved_name}")
                except Exception as e:
                    logger.error(f"Failed auto-upload of {field_name} to Cloudinary for Product #{instance.pk}: {e}")

        if updates:
            Product.objects.filter(pk=instance.pk).update(**updates)
    except Exception as e:
        logger.error(f"Error in ensure_media_on_cloudinary signal: {e}")



