from django.conf import settings
from django.db import models

from .order_models import CustomerOrder, OrderUnit, ComponentType, ComponentReservation, Component
from .models import InventoryRecord


class Installation(models.Model):
    """Apunte inmutable del acontecimiento de instalación de un componente."""
    SOURCE = [('warehouse', 'Bodega / almacén'), ('order', 'Pedido'), ('board', 'Pizarra'), ('reservation', 'Reserva')]
    reservation = models.OneToOneField(ComponentReservation, on_delete=models.PROTECT, null=True, blank=True, related_name='installation_event')
    unit = models.ForeignKey(OrderUnit, on_delete=models.PROTECT, related_name='installation_events')
    component = models.ForeignKey(Component, on_delete=models.PROTECT, related_name='installation_events')
    inventory_record = models.ForeignKey(InventoryRecord, on_delete=models.PROTECT, null=True, blank=True, related_name='installation_events')
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='signed_installations')
    installed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    source = models.CharField(max_length=16, choices=SOURCE, default='reservation', db_index=True)
    unit_serial_number = models.CharField(max_length=180, db_index=True)
    component_reference = models.CharField(max_length=200, blank=True, db_index=True)
    component_type = models.CharField(max_length=160, blank=True, db_index=True)
    inventory_table_name = models.CharField(max_length=120, blank=True)
    inventory_internal_id = models.CharField(max_length=160, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ('-installed_at', '-pk')

    def __str__(self):
        return f'{self.pk} · {self.unit_serial_number} · {self.component_reference or self.component_type}'


class OrderComponentAuthorization(models.Model):
    order = models.ForeignKey(CustomerOrder, on_delete=models.CASCADE, related_name='component_authorizations')
    component_type = models.ForeignKey(ComponentType, on_delete=models.PROTECT, related_name='order_authorizations')
    approved_quantity = models.PositiveIntegerField(default=0)
    unlimited = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='component_authorizations_updated')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['order', 'component_type'], name='unique_order_component_authorization')]

    def __str__(self):
        return f'{self.order} · {self.component_type}'


class ComponentIncreaseRequest(models.Model):
    STATUS = [('pending', 'Pendiente'), ('approved', 'Aprobada'), ('rejected', 'Rechazada'), ('fulfilled', 'Atendida')]
    order = models.ForeignKey(CustomerOrder, on_delete=models.CASCADE, related_name='component_increase_requests')
    unit = models.ForeignKey(OrderUnit, on_delete=models.PROTECT, related_name='component_increase_requests')
    component_type = models.ForeignKey(ComponentType, on_delete=models.PROTECT, related_name='increase_requests')
    requested_quantity = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=12, choices=STATUS, default='pending', db_index=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='component_increase_requests')
    requested_at = models.DateTimeField(auto_now_add=True, db_index=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='component_increase_requests_resolved')
    resolved_at = models.DateTimeField(null=True, blank=True)
    observations = models.TextField(blank=True)

    class Meta:
        ordering = ('-requested_at', '-pk')

    def __str__(self):
        return f'{self.order} · {self.component_type} · {self.get_status_display()}'


class ReservationAllocation(models.Model):
    SOURCE = [('warehouse', 'Bodega'), ('order', 'Componentes autorizados del pedido')]
    reservation = models.OneToOneField(ComponentReservation, on_delete=models.CASCADE, related_name='allocation')
    order = models.ForeignKey(CustomerOrder, on_delete=models.PROTECT, related_name='component_allocations')
    source = models.CharField(max_length=16, choices=SOURCE, db_index=True)
    authorization = models.ForeignKey(OrderComponentAuthorization, on_delete=models.PROTECT, null=True, blank=True, related_name='allocations')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.reservation_id} · {self.get_source_display()}'
