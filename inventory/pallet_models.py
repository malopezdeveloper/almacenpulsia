from django.conf import settings
from django.db import models
from .order_models import OrderUnit


class Pallet(models.Model):
    STATUS_OPEN = 'open'
    STATUS_SHIPPED = 'shipped'
    STATUS = [
        (STATUS_OPEN, 'Abierto'),
        (STATUS_SHIPPED, 'Enviado'),
    ]

    status = models.CharField(max_length=12, choices=STATUS, default=STATUS_OPEN, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='pallets_created')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    shipped_at = models.DateTimeField(null=True, blank=True, db_index=True)
    recipient = models.CharField(max_length=250, blank=True)
    shipping_data = models.JSONField(default=dict, blank=True)
    shipped_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='pallets_shipped')

    class Meta:
        ordering = ('-id',)

    @property
    def code(self):
        return f'PALET {self.pk:04d}' if self.pk else 'PALET'

    @property
    def unit_count(self):
        return self.units.count()

    @property
    def order_count(self):
        return self.units.values('unit__order_id').distinct().count()

    def __str__(self):
        return self.code


class PalletUnit(models.Model):
    pallet = models.ForeignKey(Pallet, on_delete=models.PROTECT, related_name='units')
    unit = models.OneToOneField(OrderUnit, on_delete=models.PROTECT, related_name='pallet_membership')
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='pallet_units_added')
    added_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ('added_at', 'id')

    def __str__(self):
        return f'{self.pallet.code} · {self.unit.serial_number}'
