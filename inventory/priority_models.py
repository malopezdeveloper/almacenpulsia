from django.conf import settings
from django.db import models

from .models import ProductionZone
from .order_models import CustomerOrder


class BoardPriority(models.Model):
    """Prioridad operativa de un pedido para todas las zonas o una zona concreta."""
    order = models.ForeignKey(CustomerOrder, on_delete=models.CASCADE, related_name='board_priorities')
    zone = models.ForeignKey(ProductionZone, on_delete=models.CASCADE, null=True, blank=True, related_name='board_priorities')
    active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='board_priorities_created')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('zone__position', 'zone__name', 'order__name', 'pk')
        constraints = [models.UniqueConstraint(fields=['order', 'zone'], name='unique_board_priority_order_zone')]

    def __str__(self):
        return f'{self.order.name} · {self.zone.name if self.zone_id else "Todas las zonas"}'
