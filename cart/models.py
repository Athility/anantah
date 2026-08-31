from django.db import models

class Address(models.Model):
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, db_column='user_id')
    label = models.CharField(max_length=50, null=True, blank=True)
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=15)
    line1 = models.CharField(max_length=255)
    line2 = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default='India')

    class Meta:
        db_table = 'addresses'

    def __str__(self):
        return f"{self.full_name} - {self.city}"


class CartItem(models.Model):
    buyer = models.ForeignKey('accounts.BuyerProfile', on_delete=models.CASCADE, db_column='buyer_id')
    product = models.ForeignKey('listings.Product', on_delete=models.CASCADE, db_column='product_id')
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'cart_items'
        unique_together = ('buyer', 'product')

    def __str__(self):
        return f"Cart: {self.buyer.user.username} - {self.product.title_en}"


class Order(models.Model):
    STATUS_CHOICES = (
        ('created', 'Created'),
        ('payment_received', 'Payment Received'),
        ('awaiting_artisan_shipment', 'Awaiting Artisan Shipment'),
        ('in_transit_to_hub', 'In Transit to Hub'),
        ('at_hub_verification', 'At Hub Verification'),
        ('verification_failed', 'Verification Failed'),
        ('payout_released', 'Payout Released'),
        ('in_transit_to_buyer', 'In Transit to Buyer'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
    )

    buyer = models.ForeignKey('accounts.BuyerProfile', on_delete=models.CASCADE, db_column='buyer_id', related_name='buyer_orders')
    product = models.ForeignKey('listings.Product', on_delete=models.CASCADE, db_column='product_id')
    artisan = models.ForeignKey('accounts.ArtisanProfile', on_delete=models.CASCADE, db_column='artisan_id', related_name='artisan_orders')
    shipping_address = models.ForeignKey(Address, on_delete=models.CASCADE, db_column='shipping_address_id')
    quantity = models.IntegerField(default=1)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default='INR')
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='payment_received')
    hub_id = models.IntegerField(null=True, blank=True)
    artisan_tracking_number = models.CharField(max_length=100, null=True, blank=True)
    courier_tracking_number = models.CharField(max_length=100, null=True, blank=True)
    payout_released_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    # ── Cost-breakdown fields (added for checkout summary) ─────────────────────
    # PLACEHOLDER: shipping_cost is a flat ₹80 per order until real courier rates are integrated
    # PLACEHOLDER: platform_commission is 5% of product_total until the real rate is configured
    product_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    platform_commission = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_payable = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        db_table = 'orders'

    def __str__(self):
        return f"Order #{self.id} - {self.buyer.username} - {self.status}"
