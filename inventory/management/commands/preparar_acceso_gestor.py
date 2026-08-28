import hashlib
import os
import secrets
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from inventory.models import AuditLog, UserProfile


class Command(BaseCommand):
    help = "Crea/localiza el Gestor, invalida su contraseña y genera un acceso inicial de un solo uso."

    def add_arguments(self, parser):
        parser.add_argument("--token-file", required=True)
        parser.add_argument("--username", default="gestor")
        parser.add_argument("--minutes", type=int, default=15)

    def handle(self, *args, **options):
        User = get_user_model()
        username = (options["username"] or "gestor").strip() or "gestor"
        token_file = Path(options["token_file"]).resolve()
        minutes = max(2, min(options["minutes"], 60))

        gestor = User.objects.filter(is_superuser=True).order_by("date_joined", "pk").first()
        created = gestor is None
        if gestor is None:
            if User.objects.filter(username__iexact=username).exists():
                raise CommandError(f"El usuario '{username}' ya existe pero no es Gestor. Revise la cuenta antes de continuar.")
            gestor = User(username=username)

        gestor.is_active = True
        gestor.is_staff = True
        gestor.is_superuser = True
        gestor.set_unusable_password()
        gestor.save()

        profile, _ = UserProfile.objects.get_or_create(user=gestor)
        raw_token = secrets.token_urlsafe(48)
        profile.bootstrap_token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        profile.bootstrap_expires_at = timezone.now() + timedelta(minutes=minutes)
        profile.bootstrap_used_at = None
        profile.must_change_password = False
        profile.password_reset_requested_at = None
        profile.password_reset_authorized_at = None
        profile.save()

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(raw_token, encoding="utf-8")
        try:
            os.chmod(token_file, 0o600)
        except OSError:
            pass

        AuditLog.objects.create(
            user=gestor,
            action="gestor_bootstrap_prepared",
            object_type="User",
            object_id=str(gestor.pk),
            details={"created": created, "expires_minutes": minutes},
        )
        self.stdout.write(self.style.SUCCESS(
            f"Gestor {'creado' if created else 'preparado'}: {gestor.get_username()}. Contraseña invalidada; acceso inicial de un solo uso generado."
        ))
