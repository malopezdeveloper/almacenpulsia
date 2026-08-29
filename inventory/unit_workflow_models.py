from django.conf import settings
from django.db import models

from .models import ProductionZone
from .order_models import OrderUnit, ComponentReservation, Repair, ProcurementAlert


class UnitIntervention(models.Model):
    SOURCES = [('local', 'Lote/Pedido local'), ('aiken', 'AIKEN'), ('manual', 'Alta manual confirmada')]
    unit = models.ForeignKey(OrderUnit, on_delete=models.PROTECT, related_name='interventions')
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='unit_interventions')
    zone = models.ForeignKey(ProductionZone, on_delete=models.PROTECT, related_name='unit_interventions')
    source = models.CharField(max_length=12, choices=SOURCES, default='local', db_index=True)
    source_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ('-created_at', '-pk')
        indexes = [models.Index(fields=['unit', 'created_at'], name='unit_intervention_idx')]

    def __str__(self):
        return f'{self.unit.serial_number} · {self.zone.name} · {self.worker.get_username()}'


class UnitAlertOrigin(models.Model):
    alert = models.OneToOneField(ProcurementAlert, on_delete=models.CASCADE, related_name='origin_trace')
    intervention = models.ForeignKey(UnitIntervention, on_delete=models.PROTECT, related_name='alerts')
    origin_worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='unit_alerts_originated')
    origin_zone = models.ForeignKey(ProductionZone, on_delete=models.PROTECT, related_name='unit_alerts_originated')
    created_at = models.DateTimeField(auto_now_add=True)


class ReservationInstallation(models.Model):
    reservation = models.OneToOneField(ComponentReservation, on_delete=models.CASCADE, related_name='installation_trace')
    intervention = models.ForeignKey(UnitIntervention, on_delete=models.PROTECT, null=True, blank=True, related_name='component_installations')
    installed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='component_installation_events')
    installed_at = models.DateTimeField(auto_now_add=True)


class RepairConfirmation(models.Model):
    repair = models.OneToOneField(Repair, on_delete=models.CASCADE, related_name='confirmation')
    intervention = models.ForeignKey(UnitIntervention, on_delete=models.PROTECT, null=True, blank=True, related_name='repair_confirmations')
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='repair_confirmations')
    confirmed_at = models.DateTimeField(auto_now_add=True)
    observations = models.TextField(blank=True)
