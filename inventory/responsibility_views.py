from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.shortcuts import redirect, render

from .responsibility_models import AreaResponsibility, AreaResponsibilityHistory


@login_required
@user_passes_test(lambda u: u.is_superuser)
def responsibilities_manager(request):
    User = get_user_model()
    if request.method == "POST":
        responsibility = request.POST.get("responsibility", "").strip()
        valid = dict(AreaResponsibility.RESPONSIBILITIES)
        if responsibility not in valid:
            messages.error(request, "Responsabilidad no válida.")
            return redirect("responsibilities_manager")

        user_id = request.POST.get("user", "").strip()
        with transaction.atomic():
            current = AreaResponsibility.objects.select_for_update().filter(responsibility=responsibility).first()
            if not user_id:
                if current:
                    old_user = current.user
                    AreaResponsibilityHistory.objects.create(
                        responsibility=responsibility,
                        user=old_user,
                        previous_user=old_user,
                        changed_by=request.user,
                        action="unassigned",
                    )
                    current.delete()
                    messages.success(request, f"{valid[responsibility]} ha quedado sin asignar.")
                return redirect("responsibilities_manager")

            selected = User.objects.get(pk=user_id, is_active=True)
            # Todo responsable es Administrador. El Gestor conserva siempre el control total.
            if not selected.is_staff:
                selected.is_staff = True
                selected.save(update_fields=["is_staff"])

            if current and current.user_id == selected.id:
                messages.info(request, f"{selected.get_username()} ya es {valid[responsibility]}.")
                return redirect("responsibilities_manager")

            previous = current.user if current else None
            if current:
                current.user = selected
                current.assigned_by = request.user
                current.save(update_fields=["user", "assigned_by", "updated_at"])
                action = "transferred"
            else:
                AreaResponsibility.objects.create(
                    responsibility=responsibility,
                    user=selected,
                    assigned_by=request.user,
                )
                action = "assigned"

            AreaResponsibilityHistory.objects.create(
                responsibility=responsibility,
                user=selected,
                previous_user=previous,
                changed_by=request.user,
                action=action,
            )
            messages.success(request, f"{valid[responsibility]} asignado a {selected.get_username()}.")
        return redirect("responsibilities_manager")

    assignments = {x.responsibility: x for x in AreaResponsibility.objects.select_related("user", "assigned_by")}
    rows = [(code, label, assignments.get(code)) for code, label in AreaResponsibility.RESPONSIBILITIES]
    history = AreaResponsibilityHistory.objects.select_related("user", "previous_user", "changed_by")[:50]
    return render(request, "inventory/responsibilities_manager.html", {
        "responsibilities": rows,
        "users": User.objects.filter(is_active=True).order_by("username"),
        "history": history,
    })
