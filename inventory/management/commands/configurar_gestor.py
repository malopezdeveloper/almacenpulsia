import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Crea el primer usuario gestor o garantiza sus permisos máximos."

    def add_arguments(self, parser):
        parser.add_argument("--username")
        parser.add_argument("--password")
        parser.add_argument("--noinput", action="store_true")
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="Restablece únicamente la contraseña de un Gestor existente; no crea ni promueve usuarios.",
        )

    def handle(self, *args, **options):
        User = get_user_model()

        if options["reset_password"]:
            username = (options["username"] or "").strip()
            if not username and not options["noinput"]:
                managers = list(User.objects.filter(is_superuser=True).order_by("date_joined"))
                if not managers:
                    raise CommandError("No existe ningún usuario Gestor/superusuario que pueda restablecerse.")
                if len(managers) == 1:
                    default_username = managers[0].get_username()
                    username = input(
                        f"Nombre del Gestor cuya contraseña desea restablecer [{default_username}]: "
                    ).strip() or default_username
                else:
                    self.stdout.write("Gestores existentes:")
                    for manager in managers:
                        self.stdout.write(f"  - {manager.get_username()}")
                    username = input("Nombre del Gestor cuya contraseña desea restablecer: ").strip()
            if not username:
                raise CommandError("Debe indicar el usuario Gestor.")

            user = User.objects.filter(username__iexact=username).first()
            if user is None:
                raise CommandError(f"No existe el usuario '{username}'. No se ha creado ningún usuario.")
            if not user.is_superuser:
                raise CommandError(
                    f"El usuario '{user.get_username()}' existe, pero no es Gestor/superusuario. No se ha modificado."
                )

            password = options["password"]
            if not password and not options["noinput"]:
                password = getpass.getpass("Nueva contraseña del gestor (mínimo 4 caracteres): ")
                confirmation = getpass.getpass("Repita la nueva contraseña: ")
                if password != confirmation:
                    raise CommandError("Las contraseñas no coinciden.")
            if not password or len(password) < 4:
                raise CommandError("La contraseña debe tener al menos 4 caracteres.")

            user.set_password(password)
            user.save(update_fields=["password"])
            self.stdout.write(self.style.SUCCESS(
                f"Contraseña restablecida correctamente para el Gestor: {user.get_username()}"
            ))
            return

        existing_manager = User.objects.filter(is_superuser=True).order_by("date_joined").first()
        if existing_manager and not options["username"]:
            self.stdout.write(self.style.SUCCESS(
                f"El gestor ya existe: {existing_manager.get_username()}. No se ha modificado."
            ))
            return

        username = (options["username"] or "").strip()
        if not username and not options["noinput"]:
            username = input("Nombre del usuario gestor [gestor]: ").strip() or "gestor"
        if not username:
            raise CommandError("Debe indicar --username cuando se utiliza --noinput.")

        password = options["password"]
        if not password and not options["noinput"]:
            password = getpass.getpass("Contraseña del gestor (mínimo 4 caracteres): ")
            confirmation = getpass.getpass("Repita la contraseña: ")
            if password != confirmation:
                raise CommandError("Las contraseñas no coinciden.")
        if not password or len(password) < 4:
            raise CommandError("La contraseña debe tener al menos 4 caracteres.")

        user = User.objects.filter(username__iexact=username).first()
        created = user is None
        if created:
            user = User(username=username)
        user.username = username
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(
            f"Usuario gestor {'creado' if created else 'actualizado'}: {username}"
        ))
