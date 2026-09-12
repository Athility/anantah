import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from cart.models import Order
from .verified_page_generator import generate_verified_page

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Order)
def auto_generate_verified_page_on_order_paid(sender, instance, created, **kwargs):
    """
    Signal handler: Whenever an Order is saved with status 'paid',
    automatically generate the static verified product certificate page.
    """
    if instance.status == 'paid' and instance.product:
        try:
            generate_verified_page(instance.product)
        except Exception as e:
            logger.error(f"Error in auto_generate_verified_page_on_order_paid signal for Order #{instance.id}: {e}")
