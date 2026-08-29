from django.conf import settings
from django.db import models


class AreaResponsibility(models.Model):
    PRODUCTION = "production"
    PURCHASING = "purchasing"
    SALES = "sales"
    TECHNICAL = "technical"
    RESPONSIBILITIES = [
        (PRODUCTION, "Responsable de Producción"),
        (PURCHASING, "Responsable de Compras"),
        (SALES, "Responsable de Ventas"),
        (TECHNICAL, "Responsable Técnico"),
    ]

    responsibility = models.CharField(max_length=20, choices=RESPONSIBILITIES, unique=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="area_responsibilities")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="area_responsibilities_assigned")
    assigned_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("responsibility",)

    def __str__(self):
        return f"{self.get_responsibility_display()} · {self.user.get_username()}"


class AreaResponsibilityHistory(models.Model):
    ACTIONS = [("assigned", "Asignada"), ("transferred", "Transferida"), ("unassigned", "Retirada")]
    responsibility = models.CharField(max_length=20, choices=AreaResponsibility.RESPONSIBILITIES, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="area_responsibility_history")
    previous_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="area_responsibility_history_previous")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="area_responsibility_changes")
    action = models.CharField(max_length=12, choices=ACTIONS)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at", "-pk")
