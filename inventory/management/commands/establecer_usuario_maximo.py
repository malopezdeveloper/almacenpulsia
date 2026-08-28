from getpass import getpass
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from inventory.models import UserProfile

class Command(BaseCommand):
 help="Crea o actualiza la única cuenta con máximos permisos."

 def handle(self,*args,**options):
  User=get_user_model()
  username=input("Usuario de máximos permisos [root]: ").strip().lower() or "root"
  password=getpass("Contraseña (mínimo 4 caracteres): ")
  confirmation=getpass("Repita la contraseña: ")
  if len(password)<4: raise CommandError("La contraseña debe tener al menos 4 caracteres.")
  if password!=confirmation: raise CommandError("Las contraseñas no coinciden.")
  user,_=User.objects.get_or_create(username=username)
  user.is_active=True; user.is_staff=True; user.is_superuser=True; user.set_password(password); user.save()
  profile,_=UserProfile.objects.get_or_create(user=user); profile.must_change_password=False; profile.save()
  User.objects.filter(is_superuser=True).exclude(pk=user.pk).update(is_superuser=False,is_staff=True)
  User.objects.filter(username="_operador_local").exclude(pk=user.pk).delete()
  self.stdout.write(self.style.SUCCESS(f"Cuenta '{username}' configurada con máximos permisos."))
