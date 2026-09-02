from django.db import models

class WishlistItem(models.Model):
    buyer = models.ForeignKey(
        'accounts.BuyerProfile',
        on_delete=models.CASCADE,
        db_column='buyer_id',
        related_name='wishlist_items'
    )
    product = models.ForeignKey(
        'listings.Product',
        on_delete=models.CASCADE,
        db_column='product_id',
        related_name='wishlisted_by'
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'wishlist'
        unique_together = ('buyer', 'product')

    def __str__(self):
        return f"Wishlist: {self.buyer.user.username} - {self.product.title_en}"
