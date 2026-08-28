import re
import datetime
from django.conf import settings
from django.db import models
from django.utils import timezone

class UserProfile(models.Model):
 ROLES=[("guest","Invitado"),("user","Usuario")]
 user=models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="inventory_profile")
 role=models.CharField(max_length=12,choices=ROLES,default="user",db_index=True)
 must_change_password=models.BooleanField(default=False)
 password_reset_requested_at=models.DateTimeField(null=True,blank=True)
 password_reset_authorized_at=models.DateTimeField(null=True,blank=True)
 bootstrap_token_hash=models.CharField(max_length=64,blank=True)
 bootstrap_expires_at=models.DateTimeField(null=True,blank=True)
 bootstrap_used_at=models.DateTimeField(null=True,blank=True)
 created_ip=models.GenericIPAddressField(null=True,blank=True)
 archived_at=models.DateTimeField(null=True,blank=True,db_index=True)
 archived_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name="inventory_users_archived")
 archived_reason=models.CharField(max_length=300,blank=True)
 created_at=models.DateTimeField(auto_now_add=True)
 updated_at=models.DateTimeField(auto_now=True)
 @property
 def is_guest(self): return self.role=="guest" and not self.user.is_staff and not self.user.is_superuser
 def __str__(self): return self.user.get_username()

class AccessUpgradeRequest(models.Model):
 STATUS=[("pending","Pendiente"),("approved","Aprobada"),("denied","Denegada")]
 user=models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="access_upgrade_request")
 requested_ip=models.GenericIPAddressField(null=True,blank=True)
 status=models.CharField(max_length=12,choices=STATUS,default="pending",db_index=True)
 requested_at=models.DateTimeField(auto_now_add=True,db_index=True)
 decided_at=models.DateTimeField(null=True,blank=True)
 decided_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name="access_upgrade_decisions")
 decision_note=models.CharField(max_length=300,blank=True)
 class Meta: ordering=("-requested_at","-pk")
 def __str__(self): return f"{self.user.get_username()} · {self.get_status_display()}"

class BackupSchedule(models.Model):
 enabled=models.BooleanField(default=False)
 run_time=models.TimeField(default=datetime.time(2,0))
 destination=models.CharField(max_length=500,blank=True)
 retention=models.PositiveIntegerField(default=30)
 last_run_at=models.DateTimeField(null=True,blank=True)
 last_status=models.CharField(max_length=20,blank=True)
 last_error=models.TextField(blank=True)
 updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name="backup_schedules_updated")
 updated_at=models.DateTimeField(auto_now=True)
 def __str__(self): return "Programación de backups"


class BackupDiskConfig(models.Model):
 MODES=[("disk","Disco dedicado"),("local","Directorio local")]
 mode=models.CharField(max_length=10,choices=MODES,default="disk",db_index=True)
 local_path=models.CharField(max_length=500,blank=True)
 device=models.CharField(max_length=255,blank=True)
 uuid=models.CharField(max_length=128,blank=True)
 filesystem=models.CharField(max_length=32,blank=True)
 mount_point=models.CharField(max_length=255,default="/mnt/pulsia-backup")
 last_status=models.CharField(max_length=20,blank=True)
 last_error=models.TextField(blank=True)
 updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name="backup_disk_configs_updated")
 updated_at=models.DateTimeField(auto_now=True)
 def __str__(self): return f"Backup · {self.get_mode_display()} · {self.local_path or self.device or 'sin configurar'}"

class SecurityAccessPolicy(models.Model):
 enabled=models.BooleanField(default=False)
 allowed_days=models.CharField(max_length=32,default="0,1,2,3,4")
 start_time=models.TimeField(default=datetime.time(8,0))
 end_time=models.TimeField(default=datetime.time(18,0))
 logout_before_end_seconds=models.PositiveIntegerField(default=60)
 updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name="security_policies_updated")
 created_at=models.DateTimeField(auto_now_add=True)
 updated_at=models.DateTimeField(auto_now=True)
 def __str__(self): return "Política horaria de acceso"
 @property
 def allowed_day_numbers(self):
  result=set()
  for value in (self.allowed_days or "").split(","):
   try: result.add(int(value))
   except (TypeError,ValueError): pass
  return result

class SecurityAccessEvent(models.Model):
 LEVELS=[("YELLOW","Amarilla"),("RED","Roja")]
 TYPES=[
  ("FINGERPRINT_CHANGED","Cambio de huella"),
  ("MULTIPLE_IP","Múltiples IP simultáneas"),
  ("OUT_OF_SCHEDULE","Acceso fuera de horario"),
  ("AUTO_LOGOUT","Cierre automático por horario"),
 ]
 user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="security_events")
 level=models.CharField(max_length=10,choices=LEVELS,db_index=True)
 event_type=models.CharField(max_length=50,choices=TYPES,db_index=True)
 description=models.CharField(max_length=500)
 ip=models.GenericIPAddressField(null=True,blank=True)
 previous_ip=models.GenericIPAddressField(null=True,blank=True)
 previous_data=models.JSONField(default=dict,blank=True)
 current_data=models.JSONField(default=dict,blank=True)
 reviewed=models.BooleanField(default=False,db_index=True)
 reviewed_at=models.DateTimeField(null=True,blank=True)
 reviewed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name="security_events_reviewed")
 resolution=models.CharField(max_length=40,blank=True)
 created_at=models.DateTimeField(auto_now_add=True,db_index=True)
 class Meta: ordering=("-created_at","-pk")

class ActiveSecuritySession(models.Model):
 user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="security_sessions")
 session_key=models.CharField(max_length=100,db_index=True)
 ip=models.GenericIPAddressField(null=True,blank=True,db_index=True)
 user_agent=models.TextField(blank=True)
 browser=models.CharField(max_length=120,blank=True)
 operating_system=models.CharField(max_length=120,blank=True)
 language=models.CharField(max_length=40,blank=True)
 timezone_name=models.CharField(max_length=80,blank=True)
 screen_resolution=models.CharField(max_length=40,blank=True)
 client_data=models.JSONField(default=dict,blank=True)
 fingerprint_hash=models.CharField(max_length=64,blank=True,db_index=True)
 started_at=models.DateTimeField(auto_now_add=True,db_index=True)
 last_activity=models.DateTimeField(auto_now=True,db_index=True)
 closed=models.BooleanField(default=False,db_index=True)
 closed_at=models.DateTimeField(null=True,blank=True)
 class Meta: ordering=("-last_activity","-pk")

class InventoryTable(models.Model):
 name=models.CharField(max_length=120,unique=True)
 slug=models.SlugField(max_length=140,unique=True)
 id_header=models.CharField(max_length=120,default="ID Interno")
 id_prefix=models.CharField(max_length=120,blank=True)
 id_width=models.PositiveSmallIntegerField(default=4)
 next_number=models.PositiveIntegerField(default=1)
 position=models.PositiveIntegerField(default=0)
 active=models.BooleanField(default=True)
 created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True)
 created_at=models.DateTimeField(auto_now_add=True)
 class Meta: ordering=("position","name")
 def __str__(self): return self.name
 def ensure_id_sequence(self):
  if self.id_prefix: return
  patterns={}
  for value in self.records.values_list("internal_id",flat=True):
   match=re.match(r"^(.*?)(\d+)$",value.strip())
   if match:
    prefix,digits=match.groups(); info=patterns.setdefault(prefix,{"count":0,"width":0,"maximum":0}); info["count"]+=1; info["width"]=max(info["width"],len(digits)); info["maximum"]=max(info["maximum"],int(digits))
  if patterns:
   self.id_prefix,info=max(patterns.items(),key=lambda pair:(pair[1]["count"],pair[1]["maximum"])); self.id_width=info["width"]; self.next_number=info["maximum"]+1
  else: self.id_prefix=(re.sub(r"[^A-Z0-9]","",self.name.upper())[:8] or "OBJ")+"-"
  self.save(update_fields=["id_prefix","id_width","next_number"])
 def preview_next_id(self): self.ensure_id_sequence(); return f"{self.id_prefix}{self.next_number:0{self.id_width}d}"

class InventoryField(models.Model):
 TYPES=[("text","Texto"),("number","Número"),("date","Fecha"),("bool","Sí/No")]
 table=models.ForeignKey(InventoryTable,on_delete=models.CASCADE,related_name="inventory_fields")
 name=models.CharField(max_length=160)
 key=models.SlugField(max_length=180)
 position=models.PositiveIntegerField(default=0)
 field_type=models.CharField(max_length=12,choices=TYPES,default="text")
 is_primary=models.BooleanField(default=False)
 is_destination_sn=models.BooleanField(default=False)
 is_technician=models.BooleanField(default=False)
 searchable=models.BooleanField(default=True)
 class Meta: ordering=("position",); unique_together=("table","key")
 def __str__(self): return f"{self.table} · {self.name}"

class InventoryRecord(models.Model):
 STATUS=[("available","Disponible"),("reserved","Reservado"),("loaned","Prestado"),("assigned","Entregado / instalado"),("scrapped","Baja / merma"),("incident","Incidencia")]
 table=models.ForeignKey(InventoryTable,on_delete=models.PROTECT,related_name="records")
 internal_id=models.CharField(max_length=160,db_index=True)
 data=models.JSONField(default=dict,blank=True)
 status=models.CharField(max_length=20,choices=STATUS,default="available",db_index=True)
 current_sn=models.CharField(max_length=180,blank=True,db_index=True)
 current_technician=models.CharField(max_length=160,blank=True,db_index=True)
 created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="inventory_records_created")
 created_at=models.DateTimeField(auto_now_add=True)
 updated_at=models.DateTimeField(auto_now=True)
 class Meta: ordering=("table","internal_id"); unique_together=("table","internal_id")
 def __str__(self): return f"{self.table.name} / {self.internal_id}"
 @classmethod
 def _json_safe(cls,value):
  # Defensa final: InventoryRecord puede guardarse desde formularios, importadores,
  # incidencias o código administrativo. Ningún valor de data debe provocar un 500.
  if value is None: return ""
  if isinstance(value,str): return value
  if isinstance(value,(dict,)):
   return {str(k):cls._json_safe(v) for k,v in value.items()}
  if isinstance(value,(list,tuple,set)):
   return [cls._json_safe(v) for v in value]
  if isinstance(value,(int,float,bool)):
   return str(value)
  if hasattr(value,"isoformat"):
   try: return value.isoformat()
   except Exception: pass
  return str(value)
 def save(self,*args,**kwargs):
  self.internal_id=str(self.internal_id or "").strip()
  if not self.internal_id:
   raise ValueError("El ID interno es obligatorio.")
  self.data=self._json_safe(dict(self.data or {}))
  self.current_sn=str(self.current_sn or "").strip()
  self.current_technician=str(self.current_technician or "").strip()
  return super().save(*args,**kwargs)

class RecordMovement(models.Model):
 TYPES=[("entry","Alta / importación"),("reserve","Reserva"),("loan","Préstamo"),("loan_return","Devolución préstamo"),("assign","Entrega / instalación"),("return","Devolución"),("scrap","Baja / merma"),("correction","Corrección")]
 record=models.ForeignKey(InventoryRecord,on_delete=models.PROTECT,related_name="record_movements")
 movement_type=models.CharField(max_length=20,choices=TYPES)
 occurred_at=models.DateTimeField(default=timezone.now,db_index=True)
 technician_name=models.CharField(max_length=160,blank=True,db_index=True)
 destination_sn=models.CharField(max_length=180,blank=True,db_index=True)
 reason=models.TextField(blank=True)
 registered_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
 created_at=models.DateTimeField(auto_now_add=True)
 class Meta: ordering=("-occurred_at","-pk")

class Reservation(models.Model):
 STATUS=[("pending","Pendiente de aceptación"),("accepted","Aceptada"),("delivered","Objeto entregado"),("rejected","Rechazada"),("cancelled","Cancelada"),("scrapped","Merma")]
 record=models.ForeignKey(InventoryRecord,on_delete=models.PROTECT,related_name="reservations")
 requested_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="inventory_reservations")
 destination=models.CharField(max_length=50)
 destination_sn=models.CharField(max_length=180,db_index=True)
 status=models.CharField(max_length=20,choices=STATUS,default="pending",db_index=True)
 requested_at=models.DateTimeField(auto_now_add=True,db_index=True)
 accepted_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name="inventory_reservations_accepted")
 accepted_at=models.DateTimeField(null=True,blank=True)
 resolved_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name="inventory_reservations_resolved")
 resolved_at=models.DateTimeField(null=True,blank=True)
 def get_destination_display(self):
  if not self.destination: return ""
  zone=ProductionZone.objects.filter(code=self.destination).first()
  if zone: return zone.name
  legacy={"Auditoria":"Auditoría","PlanRenove":"Renove","Direccion":"Dirección"}
  return legacy.get(self.destination,self.destination)
 class Meta:
  ordering=("-requested_at",)
  constraints=[models.UniqueConstraint(fields=["record"],condition=models.Q(status__in=["pending","accepted"]),name="one_open_reservation_per_record")]

class LoanItem(models.Model):
 STATUS=[("available","Disponible"),("pending","Solicitud pendiente"),("loaned","Prestado"),("out","Fuera de servicio"),("retired","Baja")]
 internal_id=models.CharField(max_length=120,unique=True,db_index=True)
 name=models.CharField(max_length=180)
 category=models.CharField(max_length=120,blank=True,db_index=True)
 brand=models.CharField(max_length=120,blank=True)
 model_reference=models.CharField(max_length=180,blank=True)
 serial_number=models.CharField(max_length=180,blank=True,db_index=True)
 description=models.TextField(blank=True)
 status=models.CharField(max_length=20,choices=STATUS,default="available",db_index=True)
 notes=models.TextField(blank=True)
 created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="loan_items_created")
 created_at=models.DateTimeField(auto_now_add=True)
 updated_at=models.DateTimeField(auto_now=True)
 class Meta: ordering=("category","name","internal_id")
 def __str__(self): return f"{self.internal_id} · {self.name}"

class LoanRequest(models.Model):
 STATUS=[("pending","Pendiente"),("accepted","Aceptada"),("rejected","Rechazada"),("cancelled","Cancelada")]
 item=models.ForeignKey(LoanItem,on_delete=models.PROTECT,related_name="loan_requests")
 requested_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="loan_requests")
 requested_at=models.DateTimeField(auto_now_add=True,db_index=True)
 status=models.CharField(max_length=20,choices=STATUS,default="pending",db_index=True)
 notes=models.TextField(blank=True)
 resolved_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name="loan_requests_resolved")
 resolved_at=models.DateTimeField(null=True,blank=True)
 class Meta:
  ordering=("-requested_at","-pk")
  constraints=[models.UniqueConstraint(fields=["item"],condition=models.Q(status="pending"),name="one_pending_loan_request_per_item")]
 def __str__(self): return f"{self.item.internal_id} · {self.requested_by.get_username()}"

class Loan(models.Model):
 record=models.ForeignKey(InventoryRecord,on_delete=models.PROTECT,related_name="loans",null=True,blank=True)
 loan_item=models.ForeignKey(LoanItem,on_delete=models.PROTECT,related_name="loans",null=True,blank=True)
 request=models.OneToOneField(LoanRequest,on_delete=models.PROTECT,related_name="loan",null=True,blank=True)
 borrower=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="inventory_loans_received")
 technician_name=models.CharField(max_length=160,db_index=True)
 withdrawn_at=models.DateTimeField(db_index=True)
 returned_at=models.DateTimeField(null=True,blank=True,db_index=True)
 created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="inventory_loans_created")
 returned_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name="inventory_loans_returned")
 notes=models.TextField(blank=True)
 created_at=models.DateTimeField(auto_now_add=True)
 class Meta:
  ordering=("-withdrawn_at","-pk")
  constraints=[models.UniqueConstraint(fields=["record"],condition=models.Q(returned_at__isnull=True,record__isnull=False),name="one_active_legacy_loan_per_record"),models.UniqueConstraint(fields=["loan_item"],condition=models.Q(returned_at__isnull=True,loan_item__isnull=False),name="one_active_loan_per_item")]
 def __str__(self):
  obj=self.loan_item.internal_id if self.loan_item_id else (self.record.internal_id if self.record_id else "Préstamo")
  return f"{obj} → {self.borrower.get_username()}"
 @property
 def is_active(self): return self.returned_at is None
 @property
 def object_id(self): return self.loan_item.internal_id if self.loan_item_id else (self.record.internal_id if self.record_id else "")
 @property
 def object_name(self): return self.loan_item.name if self.loan_item_id else (self.record.table.name if self.record_id else "")

class ReservationView(models.Model):
 reservation=models.ForeignKey(Reservation,on_delete=models.CASCADE,related_name="notification_views")
 user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="reservation_notification_views")
 seen_at=models.DateTimeField(auto_now_add=True)
 class Meta:
  constraints=[models.UniqueConstraint(fields=["reservation","user"],name="one_reservation_view_per_user")]

class ChatMessage(models.Model):
 sender=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="chat_messages_sent")
 recipient=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="chat_messages_received")
 body=models.TextField(max_length=4000)
 created_at=models.DateTimeField(auto_now_add=True,db_index=True)
 read_at=models.DateTimeField(null=True,blank=True,db_index=True)
 class Meta: ordering=("created_at","pk")

class LabelPrintJob(models.Model):
 STATUS=[("pending","Pendiente"),("printed","Impreso"),("failed","Error")]
 identifier=models.CharField(max_length=180,db_index=True)
 copies=models.PositiveSmallIntegerField(default=2)
 printer_name=models.CharField(max_length=255,blank=True)
 status=models.CharField(max_length=12,choices=STATUS,default="pending",db_index=True)
 error=models.TextField(blank=True)
 requested_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="label_print_jobs")
 created_at=models.DateTimeField(auto_now_add=True,db_index=True)
 completed_at=models.DateTimeField(null=True,blank=True)
 class Meta: ordering=("-created_at",)



class ClientBatchSheet(models.Model):
 name=models.CharField(max_length=160)
 next_row_number=models.PositiveBigIntegerField(default=1)
 client=models.CharField(max_length=160,blank=True,db_index=True)
 concept=models.CharField(max_length=160,blank=True,db_index=True)
 position=models.PositiveIntegerField(default=0)
 active=models.BooleanField(default=True)
 created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="client_batch_sheets_created")
 created_at=models.DateTimeField(auto_now_add=True)
 updated_at=models.DateTimeField(auto_now=True)
 class Meta:
  ordering=("client","concept","position","name")
  constraints=[models.UniqueConstraint(fields=["client","concept","name"],name="unique_client_batch_sheet_name")]
 def __str__(self): return self.name

class ClientBatchField(models.Model):
 TYPES=[("text","Texto"),("number","Número"),("date","Fecha"),("bool","Sí/No")]
 sheet=models.ForeignKey(ClientBatchSheet,on_delete=models.CASCADE,related_name="custom_fields")
 name=models.CharField(max_length=160)
 key=models.SlugField(max_length=180)
 field_type=models.CharField(max_length=12,choices=TYPES,default="text")
 position=models.PositiveIntegerField(default=0)
 active=models.BooleanField(default=True)
 created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="client_batch_fields_created")
 created_at=models.DateTimeField(auto_now_add=True)
 updated_at=models.DateTimeField(auto_now=True)
 class Meta:
  ordering=("position","pk")
  constraints=[models.UniqueConstraint(fields=["sheet","key"],name="unique_client_batch_field_key")]
 def __str__(self): return f"{self.sheet.name} · {self.name}"

class ClientBatchRow(models.Model):
 sheet=models.ForeignKey(ClientBatchSheet,on_delete=models.PROTECT,related_name="rows")
 internal_id=models.CharField(max_length=160,db_index=True)
 brand=models.CharField(max_length=160,blank=True,db_index=True)
 model_reference=models.CharField(max_length=200,blank=True,db_index=True)
 component=models.CharField(max_length=200,blank=True,db_index=True)
 reference=models.CharField(max_length=200,blank=True,db_index=True)
 units_pending=models.PositiveIntegerField(default=0)
 units_stock=models.PositiveIntegerField(default=0)
 units_sent=models.PositiveIntegerField(default=0)
 unit_price=models.DecimalField(max_digits=14,decimal_places=4,default=0)
 total_price=models.DecimalField(max_digits=16,decimal_places=2,default=0,editable=False)
 client=models.CharField(max_length=160,blank=True,db_index=True)
 observations=models.TextField(blank=True)
 extra_data=models.JSONField(default=dict,blank=True)
 created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="client_batch_rows_created")
 updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="client_batch_rows_updated")
 created_at=models.DateTimeField(auto_now_add=True,db_index=True)
 updated_at=models.DateTimeField(auto_now=True)
 class Meta:
  ordering=("sheet","internal_id")
  constraints=[models.UniqueConstraint(fields=["sheet","internal_id"],name="unique_client_batch_row_id")]
 def __str__(self): return f"{self.sheet.name} · {self.internal_id}"
 @property
 def total_units(self): return self.units_pending+self.units_stock+self.units_sent

class ClientBatchChange(models.Model):
 ACTIONS=[("sheet_created","Hoja creada"),("sheet_modified","Hoja modificada"),("field_created","Campo creado"),("field_modified","Campo modificado"),("field_disabled","Campo retirado"),("row_created","Registro creado"),("row_modified","Registro modificado")]
 sheet=models.ForeignKey(ClientBatchSheet,on_delete=models.PROTECT,related_name="changes")
 row=models.ForeignKey(ClientBatchRow,on_delete=models.PROTECT,null=True,blank=True,related_name="changes")
 field=models.ForeignKey(ClientBatchField,on_delete=models.PROTECT,null=True,blank=True,related_name="changes")
 action=models.CharField(max_length=24,choices=ACTIONS,db_index=True)
 before=models.JSONField(default=dict,blank=True)
 after=models.JSONField(default=dict,blank=True)
 changed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="client_batch_changes")
 changed_at=models.DateTimeField(auto_now_add=True,db_index=True)
 class Meta: ordering=("-changed_at","-pk")


class ServiceAccess(models.Model):
 ip_address=models.GenericIPAddressField(db_index=True)
 user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name="service_accesses")
 first_seen_at=models.DateTimeField(auto_now_add=True)
 last_seen_at=models.DateTimeField(auto_now=True,db_index=True)
 request_count=models.PositiveBigIntegerField(default=1)
 last_path=models.CharField(max_length=500,blank=True)
 last_user_agent=models.CharField(max_length=500,blank=True)
 class Meta:
  ordering=("-last_seen_at","-pk")
  constraints=[models.UniqueConstraint(fields=["ip_address","user"],name="unique_service_access_ip_user")]
 def __str__(self): return f"{self.ip_address} · {self.user.get_username() if self.user_id else 'Anónimo'}"

class IPBan(models.Model):
 ip_address=models.GenericIPAddressField(db_index=True)
 banned_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="ip_bans_created")
 banned_at=models.DateTimeField(auto_now_add=True,db_index=True)
 banned_until=models.DateTimeField(null=True,blank=True,db_index=True)
 reason=models.CharField(max_length=300,blank=True)
 revoked_at=models.DateTimeField(null=True,blank=True,db_index=True)
 revoked_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name="ip_bans_revoked")
 class Meta: ordering=("-banned_at","-pk")
 @property
 def is_active(self): return self.revoked_at is None and (self.banned_until is None or self.banned_until>timezone.now())
 def __str__(self): return f"{self.ip_address} · {'Permanente' if self.banned_until is None else self.banned_until}"

class Category(models.Model):
 name=models.CharField(max_length=100,unique=True); prefix=models.CharField(max_length=12,unique=True); active=models.BooleanField(default=True)
 def __str__(self): return self.name
class CustomField(models.Model):
 TYPES=[("text","Texto"),("number","Número"),("bool","Sí/No"),("date","Fecha"),("choice","Lista")]
 category=models.ForeignKey(Category,on_delete=models.CASCADE,related_name="fields",null=True,blank=True)
 name=models.CharField(max_length=100); key=models.SlugField(max_length=100); field_type=models.CharField(max_length=12,choices=TYPES,default="text"); required=models.BooleanField(default=False); searchable=models.BooleanField(default=True); reportable=models.BooleanField(default=True); options=models.JSONField(default=list,blank=True); active=models.BooleanField(default=True)
 class Meta: unique_together=("category","key")
class Location(models.Model):
 name=models.CharField(max_length=120,unique=True); active=models.BooleanField(default=True)
 def __str__(self): return self.name
class Technician(models.Model):
 name=models.CharField(max_length=120); employee_code=models.CharField(max_length=40,blank=True); active=models.BooleanField(default=True)
 def __str__(self): return self.name
class Item(models.Model):
 STATUS=[("available","Disponible"),("reserved","Reservado"),("assigned","Entregado / instalado"),("testing","Pendiente de prueba"),("incident","Incidencia"),("scrapped","Baja / merma")]
 internal_id=models.CharField(max_length=60,unique=True,db_index=True); category=models.ForeignKey(Category,on_delete=models.PROTECT,related_name="items"); brand=models.CharField(max_length=120,blank=True); model_reference=models.CharField(max_length=220,blank=True); serial_number=models.CharField(max_length=160,blank=True,db_index=True); status=models.CharField(max_length=20,choices=STATUS,default="available",db_index=True); location=models.ForeignKey(Location,on_delete=models.PROTECT,null=True,blank=True); destination_sn=models.CharField(max_length=160,blank=True,db_index=True); notes=models.TextField(blank=True); custom_data=models.JSONField(default=dict,blank=True); created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True); created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="items_created")
 def __str__(self): return self.internal_id
class Movement(models.Model):
 TYPES=[("entry","Alta"),("transfer","Cambio de ubicación"),("assign","Entrega / instalación"),("return","Devolución"),("reserve","Reserva"),("scrap","Merma"),("correction","Corrección")]
 item=models.ForeignKey(Item,on_delete=models.PROTECT,related_name="movements"); movement_type=models.CharField(max_length=20,choices=TYPES); occurred_at=models.DateTimeField(default=timezone.now,db_index=True); technician=models.ForeignKey(Technician,on_delete=models.PROTECT,null=True,blank=True); destination_sn=models.CharField(max_length=160,blank=True,db_index=True); from_location=models.ForeignKey(Location,on_delete=models.PROTECT,null=True,blank=True,related_name="movements_from"); to_location=models.ForeignKey(Location,on_delete=models.PROTECT,null=True,blank=True,related_name="movements_to"); reason=models.TextField(blank=True); registered_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT); created_at=models.DateTimeField(auto_now_add=True)
class Incident(models.Model):
 SEVERITY=[("info","Información"),("warning","Advertencia"),("error","Error")]; STATUS=[("pending","Pendiente"),("review","En revisión"),("resolved","Resuelta"),("ignored","Ignorada")]
 title=models.CharField(max_length=180); details=models.TextField(); kind=models.CharField(max_length=80,db_index=True); severity=models.CharField(max_length=12,choices=SEVERITY,default="warning"); status=models.CharField(max_length=12,choices=STATUS,default="pending",db_index=True); source_file=models.CharField(max_length=255,blank=True); source_sheet=models.CharField(max_length=120,blank=True); source_row=models.PositiveIntegerField(null=True,blank=True); payload=models.JSONField(default=dict,blank=True); created_at=models.DateTimeField(auto_now_add=True); resolved_at=models.DateTimeField(null=True,blank=True); resolved_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True)
class ImportJob(models.Model):
 file_name=models.CharField(max_length=255); fingerprint=models.CharField(max_length=64,db_index=True); status=models.CharField(max_length=20,default="validating"); rows_total=models.PositiveIntegerField(default=0); rows_imported=models.PositiveIntegerField(default=0); rows_incident=models.PositiveIntegerField(default=0); created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT); created_at=models.DateTimeField(auto_now_add=True)
class AuditLog(models.Model):
 user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT); action=models.CharField(max_length=100,db_index=True); object_type=models.CharField(max_length=80); object_id=models.CharField(max_length=120,blank=True); details=models.JSONField(default=dict,blank=True); created_at=models.DateTimeField(auto_now_add=True,db_index=True)

class NetworkReservationRequest(models.Model):
 STATUS=[("pending","Pendiente"),("applied","Aplicada"),("partial","Parcial"),("failed","Error")]
 ip_address=models.GenericIPAddressField(db_index=True)
 prefix_length=models.PositiveSmallIntegerField(default=24)
 gateway=models.GenericIPAddressField(null=True,blank=True)
 mac_address=models.CharField(max_length=32,blank=True,db_index=True)
 interface_name=models.CharField(max_length=160,blank=True)
 hostname=models.CharField(max_length=160,blank=True)
 platform=models.CharField(max_length=80,blank=True)
 status=models.CharField(max_length=12,choices=STATUS,default="pending",db_index=True)
 dhcp_reserved=models.BooleanField(default=False)
 dns_updated=models.BooleanField(default=False)
 details=models.JSONField(default=dict,blank=True)
 message=models.TextField(blank=True)
 requested_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="network_reservation_requests")
 requested_at=models.DateTimeField(auto_now_add=True,db_index=True)
 completed_at=models.DateTimeField(null=True,blank=True)
 class Meta: ordering=("-requested_at","-pk")
 def __str__(self): return f"{self.ip_address} · {self.get_status_display()}"




class ProductionModelMySQLSource(models.Model):
    host=models.CharField(max_length=255)
    port=models.PositiveIntegerField(default=3306)
    database=models.CharField(max_length=128)
    username=models.CharField(max_length=128)
    encrypted_password=models.TextField(blank=True)
    updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name="production_mysql_sources_updated")
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name="Origen MySQL de modelos de producción"
    def __str__(self): return f"{self.username}@{self.host}:{self.port}/{self.database}"

class ProductionModel(models.Model):
    name=models.CharField(max_length=160,unique=True,db_index=True)
    is_active=models.BooleanField(default=True,db_index=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name="production_models_created")
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=["name"]
    def __str__(self): return self.name

class ProductionModelExclusion(models.Model):
    name=models.CharField(max_length=160,unique=True,db_index=True)
    excluded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name="production_model_exclusions_created")
    reason=models.CharField(max_length=255,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=["name"]
    def __str__(self): return self.name

class ProductionProcessor(models.Model):
    name=models.CharField(max_length=160,unique=True,db_index=True)
    is_active=models.BooleanField(default=True,db_index=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name="production_processors_created")
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=["name"]
    def __str__(self): return self.name



class ProductionZone(models.Model):
 code=models.SlugField(max_length=50,unique=True,db_index=True)
 name=models.CharField(max_length=100,unique=True)
 position=models.PositiveIntegerField(default=0,db_index=True)
 is_active=models.BooleanField(default=True,db_index=True)
 created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name="production_zones_created")
 created_at=models.DateTimeField(auto_now_add=True)
 updated_at=models.DateTimeField(auto_now=True)
 class Meta:
  ordering=["position","name"]
 def __str__(self): return self.name

 def save(self,*args,**kwargs):
  self.name=" ".join((self.name or "").strip().split())
  self.code=(self.code or "").strip().lower()
  return super().save(*args,**kwargs)

class ProductionEntry(models.Model):
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    date=models.DateField(default=datetime.date.today, db_index=True)
    hour=models.PositiveSmallIntegerField(default=0)
    model_name=models.CharField(max_length=160)
    production_model=models.ForeignKey(ProductionModel,on_delete=models.PROTECT,related_name="entries")
    ram_gb=models.PositiveIntegerField(null=True,blank=True)
    disk_gb=models.PositiveIntegerField(null=True,blank=True)
    processor=models.ForeignKey(ProductionProcessor,on_delete=models.PROTECT,null=True,blank=True,related_name="entries")
    processor_name=models.CharField(max_length=160,blank=True)
    origin_zone=models.CharField(max_length=50, db_index=True)
    zone=models.CharField(max_length=50, db_index=True, help_text="Zona de destino")
    quantity=models.PositiveIntegerField(default=1)
    created_at=models.DateTimeField(auto_now_add=True)
    @staticmethod
    def _zone_label(value):
        if not value: return ""
        zone=ProductionZone.objects.filter(code=value).first()
        if zone: return zone.name
        legacy={"Auditoria":"Auditoría","PlanRenove":"Renove","Direccion":"Dirección"}
        return legacy.get(value,value)
    def get_origin_zone_display(self): return self._zone_label(self.origin_zone)
    def get_zone_display(self): return self._zone_label(self.zone)
    class Meta:
        ordering=["-created_at"]
        indexes=[
            models.Index(fields=["date","hour"],name="prod_date_hour_idx"),
            models.Index(fields=["user","date"],name="prod_user_date_idx"),
            models.Index(fields=["zone","date"],name="prod_zone_date_idx"),
        ]
