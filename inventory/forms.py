from django import forms
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
import re
from collections import Counter
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.contrib.auth import get_user_model
from .models import InventoryTable,InventoryField,InventoryRecord,Reservation,ProductionZone,Loan,LoanItem,LoanRequest,ClientBatchSheet,ClientBatchField,ClientBatchRow

class PasswordChangeRequiredForm(forms.Form):
 password=forms.CharField(min_length=4,label="Nueva contraseña",widget=forms.PasswordInput)
 password_confirm=forms.CharField(min_length=4,label="Repetir contraseña",widget=forms.PasswordInput)
 def clean(self):
  data=super().clean()
  if data.get("password")!=data.get("password_confirm"): self.add_error("password_confirm","Las contraseñas no coinciden.")
  return data

class InventoryTableForm(forms.ModelForm):
 class Meta: model=InventoryTable; fields=["name"]
 def save(self,commit=True):
  obj=super().save(False); base=slugify(obj.name) or "tabla"; slug=base; n=2
  while InventoryTable.objects.exclude(pk=obj.pk).filter(slug=slug).exists(): slug=f"{base}-{n}"; n+=1
  obj.slug=slug
  if not obj.id_prefix:
   obj.id_prefix=(re.sub(r"[^A-Z0-9]","",obj.name.upper())[:8] or "OBJ")+"-"
   obj.id_width=4
  if commit: obj.save()
  return obj

class InventoryFieldForm(forms.ModelForm):
 class Meta: model=InventoryField; fields=["table","name","field_type","is_destination_sn","is_technician","searchable"]
 def save(self,commit=True):
  obj=super().save(False); base=slugify(obj.name).replace("-","_") or "campo"; key=base; n=2
  while InventoryField.objects.filter(table=obj.table,key=key).exists(): key=f"{base}_{n}"; n+=1
  obj.key=key; obj.position=obj.table.inventory_fields.count()+1
  if commit: obj.save()
  return obj

class DatalistTextInput(forms.TextInput):
 def __init__(self,*args,options=None,datalist_id=None,**kwargs):
  self.options=list(options or [])
  self.datalist_id=datalist_id
  attrs=kwargs.setdefault("attrs",{})
  if self.datalist_id: attrs["list"]=self.datalist_id
  attrs.setdefault("style","text-transform:uppercase")
  super().__init__(*args,**kwargs)
 def render(self,name,value,attrs=None,renderer=None):
  base=super().render(name,value,attrs,renderer)
  if not self.datalist_id or not self.options: return base
  options="".join(f'<option value="{escape(str(v))}"></option>' for v in self.options)
  return mark_safe(f'{base}<datalist id="{escape(self.datalist_id)}">{options}</datalist>')

class DynamicRecordForm(forms.Form):
 EXCLUDED_TEXT_TOKENS={"id"}
 def __init__(self,table,*args,instance=None,allow_reentry=False,**kwargs):
  self.table=table; self.instance=instance; self.allow_reentry=allow_reentry; self.reentry_record=None; self.reactivated=False; super().__init__(*args,**kwargs)
  initial_data=dict(instance.data or {}) if instance else {}
  for field in table.inventory_fields.filter(is_primary=False):
   label=(f"{field.key} {field.name}").casefold()
   widget=forms.Textarea(attrs={"rows":2}) if ("nota" in label or "compatible" in label or "observ" in label) else DatalistTextInput(options=self.repeated_values(field),datalist_id=f"field_values_{field.pk}")
   # Todos los campos dinámicos son deliberadamente flexibles. field_type describe
   # el dato esperado, pero nunca debe impedir registrar el valor real recibido.
   form_field=forms.CharField(required=False,label=field.name,widget=widget)
   initial=initial_data.get(field.key,"")
   form_field.initial=self.safe_text(initial)
   self.fields[field.key]=form_field

 @staticmethod
 def safe_text(value):
  if value is None: return ""
  if isinstance(value,str): return value
  if hasattr(value,"isoformat"):
   try: return value.isoformat()
   except Exception: pass
  return str(value)

 def repeated_values(self,field):
  counter=Counter()
  for data in InventoryRecord.objects.filter(table=self.table).values_list("data",flat=True):
   value=(data or {}).get(field.key)
   text=self.safe_text(value).strip()
   if text: counter[text]+=1
  return sorted(value for value,count in counter.items() if count>=3)

 def save(self,user):
  # La reserva del identificador y la escritura del registro forman una única
  # transacción. Si el INSERT falla, next_number vuelve atrás y no se pierde ID.
  with transaction.atomic():
   if self.instance:
    record=InventoryRecord.objects.select_for_update().get(pk=self.instance.pk)
    immutable_id=record.internal_id
   else:
    table=InventoryTable.objects.select_for_update().get(pk=self.table.pk)
    internal_id=table.preview_next_id()
    while InventoryRecord.objects.filter(table=table,internal_id__iexact=internal_id).exists():
     table.next_number+=1; internal_id=table.preview_next_id()
    table.next_number+=1; table.save(update_fields=["next_number"])
    record=InventoryRecord(table=table,internal_id=internal_id,created_by=user)
    immutable_id=internal_id; self.table=table

   data=dict(record.data or {})
   for field in self.table.inventory_fields.filter(is_primary=False):
    # Nunca se toma el ID desde POST; los demás valores se conservan como texto.
    data[field.key]=self.safe_text(self.cleaned_data.get(field.key,"")).strip()
   record.data=data
   record.internal_id=immutable_id

   # Los campos auxiliares se sincronizan solo si la estructura los identifica.
   sn_field=self.table.inventory_fields.filter(is_primary=False,is_destination_sn=True).first()
   tech_field=self.table.inventory_fields.filter(is_primary=False,is_technician=True).first()
   if sn_field: record.current_sn=self.safe_text(data.get(sn_field.key,"")).strip()
   if tech_field: record.current_technician=self.safe_text(data.get(tech_field.key,"")).strip()

   if self.reactivated:
    record.status="available"
    now=timezone.now(); record.reservations.filter(status="pending").update(status="cancelled",resolved_by=user,resolved_at=now)
   elif not self.instance:
    record.status="available"

   record.save()
   return record

class RecordAssignmentForm(forms.Form):
 object_query=forms.CharField(max_length=160,label="Buscar objeto",help_text="Busque por referencia, marca, modelo, número de serie o cualquier dato conocido.")
 record_pk=forms.IntegerField(required=False,widget=forms.HiddenInput)
 occurred_at=forms.DateTimeField(label="Fecha",widget=forms.DateTimeInput(attrs={"type":"datetime-local"}))
 technician=forms.CharField(max_length=160,label="Técnico")
 destination_sn=forms.CharField(max_length=180,label="SN destino")
 reason=forms.CharField(required=False,label="Observaciones",widget=forms.Textarea)
 def clean(self):
  data=super().clean(); pk=data.get("record_pk"); typed=(data.get("object_query") or "").strip(); qs=InventoryRecord.objects.exclude(status="scrapped").select_related("table")
  record=qs.filter(pk=pk).first() if pk else None
  if not record:
   exact=list(qs.filter(internal_id__iexact=typed)[:2])
   if len(exact)==1: record=exact[0]
   elif len(exact)>1: self.add_error("object_query","Hay varias coincidencias; seleccione uno de los resultados.")
   else: self.add_error("object_query","No se encontró un objeto activo con ese criterio.")
  data["record"]=record; return data

class RecordScrapForm(forms.Form):
 record=forms.ModelChoiceField(InventoryRecord.objects.exclude(status="scrapped").select_related("table"),label="Objeto")
 occurred_at=forms.DateTimeField(label="Fecha",widget=forms.DateTimeInput(attrs={"type":"datetime-local"}))
 reason=forms.CharField(label="Motivo",widget=forms.Textarea)
 confirm=forms.BooleanField(label="Confirmo la baja del objeto")

class ReservationForm(forms.Form):
 destination=forms.ChoiceField(label="Destino",choices=())
 destination_sn=forms.CharField(label="SN de la máquina de destino",max_length=180)
 def __init__(self,*args,**kwargs):
  super().__init__(*args,**kwargs)
  self.fields["destination"].choices=[(z.code,z.name) for z in ProductionZone.objects.filter(is_active=True).order_by("position","name")]

class ExistingLabelReprintForm(forms.Form):
 record=forms.ModelChoiceField(queryset=InventoryRecord.objects.none(),label="Objeto existente")
 def __init__(self,*args,**kwargs):
  super().__init__(*args,**kwargs)
  self.fields["record"].queryset=InventoryRecord.objects.exclude(status="scrapped").select_related("table").order_by("table__name","internal_id")
 def identifier(self):
  return self.cleaned_data["record"].internal_id

class LabelSequenceForm(forms.Form):
 start_id=forms.CharField(max_length=180,label="ID inicial",help_text="Ej.: RAM-00100")
 end_id=forms.CharField(max_length=180,label="ID final",help_text="Ej.: RAM-00120")
 copies=forms.ChoiceField(label="Copias por ID",choices=(("1","1 copia"),("2","2 copias")),initial="2")
 confirm=forms.BooleanField(label="Confirmo la impresión de la secuencia completa")
 MAX_IDS=5000
 _pattern=re.compile(r"^(.*?)(\d+)$")
 def clean(self):
  data=super().clean(); start=(data.get("start_id") or "").strip(); end=(data.get("end_id") or "").strip()
  ms=self._pattern.match(start); me=self._pattern.match(end)
  if not ms: self.add_error("start_id","El ID inicial debe terminar en una parte numérica.")
  if not me: self.add_error("end_id","El ID final debe terminar en una parte numérica.")
  if not ms or not me: return data
  prefix_s,num_s=ms.groups(); prefix_e,num_e=me.groups()
  if prefix_s!=prefix_e:
   self.add_error("end_id","El ID inicial y final deben tener el mismo prefijo."); return data
  if len(num_s)!=len(num_e):
   self.add_error("end_id","La parte numérica inicial y final debe tener la misma longitud."); return data
  first,last=int(num_s),int(num_e)
  if last<first:
   self.add_error("end_id","El ID final no puede ser menor que el inicial."); return data
  count=last-first+1
  if count>self.MAX_IDS:
   self.add_error("end_id",f"La secuencia no puede superar {self.MAX_IDS} identificadores por trabajo."); return data
  data["_sequence"]=(prefix_s,first,last,len(num_s)); data["count"]=count; data["copies_int"]=int(data.get("copies") or 2)
  return data
 def identifiers(self):
  prefix,first,last,width=self.cleaned_data["_sequence"]
  return [f"{prefix}{n:0{width}d}" for n in range(first,last+1)]


class LoanRequestForm(forms.Form):
 item=forms.ModelChoiceField(queryset=LoanItem.objects.none(),label="Item prestable")
 notes=forms.CharField(required=False,label="Observaciones para la solicitud",widget=forms.Textarea(attrs={"rows":2}))
 def __init__(self,*args,**kwargs):
  super().__init__(*args,**kwargs)
  self.fields["item"].queryset=LoanItem.objects.filter(status="available").order_by("category","name","internal_id")

class LoanItemForm(forms.ModelForm):
 class Meta:
  model=LoanItem
  fields=("name","category","brand","model_reference","serial_number","description","notes")
  labels={"name":"Nombre","category":"Categoría / tipo","brand":"Marca","model_reference":"Modelo","serial_number":"Número de serie","description":"Descripción","notes":"Observaciones"}
  widgets={"description":forms.Textarea(attrs={"rows":2}),"notes":forms.Textarea(attrs={"rows":2})}


class ClientBatchSheetForm(forms.ModelForm):
 class Meta:
  model=ClientBatchSheet
  fields=("name","client","concept")
  labels={"name":"Pedido","client":"Proveedor","concept":"Cliente"}

class ClientBatchFieldForm(forms.ModelForm):
 class Meta:
  model=ClientBatchField
  fields=("name","field_type")
  labels={"name":"Nombre del campo","field_type":"Tipo"}

class ClientBatchRowForm(forms.ModelForm):
 class Meta:
  model=ClientBatchRow
  fields=("brand","model_reference","component","reference","units_pending","units_stock","units_sent","unit_price","client","observations")
  labels={"brand":"Marca","model_reference":"Modelo","component":"Componente","reference":"Referencia","units_pending":"UD pendientes","units_stock":"Stock","units_sent":"UD enviadas","unit_price":"Precio unitario","client":"Cliente","observations":"Observaciones"}
  widgets={"observations":forms.Textarea(attrs={"rows":2})}
 def __init__(self,*args,sheet=None,**kwargs):
  self.sheet=sheet or getattr(kwargs.get("instance"),"sheet",None)
  super().__init__(*args,**kwargs)
  if self.sheet and not self.initial.get("client"): self.fields["client"].initial=self.sheet.client


class DuplicateIncidentResolutionForm(forms.Form):
 """Resolución explícita de incidencias por ID duplicado.

 La aplicación presenta los datos, pero no decide la resolución: el usuario
 elige si corrige el registro existente o crea uno nuevo y define los valores
 que se aplicarán.
 """
 ACTIONS=(
  ("update_existing","Modificar el registro existente"),
  ("create_new","Crear un registro nuevo con otro identificador"),
 )
 resolution_action=forms.ChoiceField(label="Resolución propuesta",choices=ACTIONS,widget=forms.RadioSelect)
 new_internal_id=forms.CharField(required=False,max_length=160,label="Nuevo identificador")
 resolution_note=forms.CharField(required=True,label="Motivo / explicación de la propuesta",widget=forms.Textarea(attrs={"rows":3}))
 print_labels=forms.BooleanField(required=False,label="Imprimir 2 etiquetas al aplicar la propuesta")

 def __init__(self,table,*args,existing_record=None,incoming_payload=None,**kwargs):
  self.table=table
  self.existing_record=existing_record
  self.incoming_payload=incoming_payload or {}
  super().__init__(*args,**kwargs)
  if existing_record is None:
   self.fields["resolution_action"].choices=(("create_new","Crear un registro nuevo con otro identificador"),)
   self.fields["resolution_action"].initial="create_new"
  else:
   self.fields["resolution_action"].initial="update_existing"
  for field in table.inventory_fields.filter(is_primary=False):
   current=(existing_record.data or {}).get(field.key,"") if existing_record else ""
   incoming=self.incoming_payload.get(field.name,current)
   self.fields[f"existing_{field.key}"]=self._field_for(field,current,f"Propuesta · {field.name}")
   self.fields[f"new_{field.key}"]=self._field_for(field,incoming,f"Nuevo registro · {field.name}")

 @staticmethod
 def _field_for(field,initial,label):
  # En la resolución de incidencias los datos deben poder conservarse tal y
  # como llegan del origen. Los campos dinámicos se almacenan en JSON y no
  # deben provocar un HTTP 500 ni bloquear una corrección porque el catálogo
  # los hubiera definido previamente como número/fecha/bool.
  # El único valor con semántica rígida es el ID, tratado fuera de este método.
  ff=forms.CharField(required=False,label=label,widget=forms.TextInput())
  ff.initial=initial
  return ff

 @staticmethod
 def json_value(value):
  if hasattr(value,"isoformat") and not isinstance(value,str): return value.isoformat()
  try:
   from decimal import Decimal
   if isinstance(value,Decimal): return float(value)
  except Exception:
   pass
  return value if value is not None else ""

 def proposed_data(self,prefix):
  data={}
  for field in self.table.inventory_fields.filter(is_primary=False):
   data[field.key]=self.json_value(self.cleaned_data.get(f"{prefix}_{field.key}",""))
  return data

 def clean(self):
  data=super().clean(); action=data.get("resolution_action")
  if action=="update_existing":
   if self.existing_record is None:
    self.add_error("resolution_action","No existe un registro de esta tabla que pueda modificarse.")
   elif not self.errors:
    proposed=self.proposed_data("existing")
    current=dict(self.existing_record.data or {})
    normalized_current={f.key:self.json_value(current.get(f.key,"")) for f in self.table.inventory_fields.filter(is_primary=False)}
    if proposed==normalized_current:
     self.add_error("resolution_action","La propuesta no contiene ningún cambio respecto al registro existente.")
  elif action=="create_new":
   new_id=(data.get("new_internal_id") or "").strip()
   if not new_id:
    self.add_error("new_internal_id","Indique el identificador que desea asignar al nuevo registro.")
   elif InventoryRecord.objects.filter(internal_id__iexact=new_id).exists():
    self.add_error("new_internal_id","Ese identificador ya existe. Elija otro distinto.")
   data["new_internal_id"]=new_id
  return data
