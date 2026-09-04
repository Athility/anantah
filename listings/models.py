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
    price = models.DecimalField(max_digits=10, decimal_places=2)
    raw_image = models.ImageField(upload_to='products/raw/', max_length=255)
    refined_image = models.ImageField(upload_to='products/refined/', max_length=255, null=True, blank=True)
    raw_audio = models.FileField(upload_to='products/audio/', storage=get_audio_storage, max_length=255, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'products'

    def __str__(self):
        return self.title_en

from django.db.models.signals import post_delete
from django.dispatch import receiver
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

