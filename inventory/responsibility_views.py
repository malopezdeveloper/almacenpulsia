from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required,user_passes_test
from django.db import transaction
from django.shortcuts import redirect,render
from .responsibility_models import AreaResponsibility,AreaResponsibilityHistory


def _demote_if_only_responsibility_staff(user):
    if not user or user.is_superuser:return
    if AreaResponsibility.objects.filter(user=user).exists():return
    # Los roles de negocio no requieren is_staff; al perder la última responsabilidad
    # se elimina el privilegio administrativo residual.
    if user.is_staff:user.is_staff=False;user.save(update_fields=['is_staff'])

@login_required
@user_passes_test(lambda u:u.is_superuser)
def responsibilities_manager(request):
 User=get_user_model()
 if request.method=='POST':
  responsibility=request.POST.get('responsibility','').strip();valid=dict(AreaResponsibility.RESPONSIBILITIES)
  if responsibility not in valid:messages.error(request,'Responsabilidad no válida.');return redirect('responsibilities_manager')
  user_id=request.POST.get('user','').strip()
  with transaction.atomic():
   current=AreaResponsibility.objects.select_for_update().filter(responsibility=responsibility).first()
   if not user_id:
    if current:
     old=current.user;AreaResponsibilityHistory.objects.create(responsibility=responsibility,user=old,previous_user=old,changed_by=request.user,action='unassigned');current.delete();_demote_if_only_responsibility_staff(old);messages.success(request,f'{valid[responsibility]} ha quedado sin asignar.')
    return redirect('responsibilities_manager')
   selected=User.objects.filter(pk=user_id,is_active=True).first()
   if not selected:messages.error(request,'Usuario no válido o inactivo.');return redirect('responsibilities_manager')
   if not selected.is_staff:selected.is_staff=True;selected.save(update_fields=['is_staff'])
   if current and current.user_id==selected.id:messages.info(request,f'{selected.get_username()} ya es {valid[responsibility]}.');return redirect('responsibilities_manager')
   previous=current.user if current else None
   if current:current.user=selected;current.assigned_by=request.user;current.save(update_fields=['user','assigned_by','updated_at']);action='transferred'
   else:AreaResponsibility.objects.create(responsibility=responsibility,user=selected,assigned_by=request.user);action='assigned'
   AreaResponsibilityHistory.objects.create(responsibility=responsibility,user=selected,previous_user=previous,changed_by=request.user,action=action)
   if previous and previous.pk!=selected.pk:_demote_if_only_responsibility_staff(previous)
   messages.success(request,f'{valid[responsibility]} asignado a {selected.get_username()}.')
  return redirect('responsibilities_manager')
 assignments={x.responsibility:x for x in AreaResponsibility.objects.select_related('user','assigned_by')};rows=[(code,label,assignments.get(code)) for code,label in AreaResponsibility.RESPONSIBILITIES]
 return render(request,'inventory/responsibilities_manager.html',{'responsibilities':rows,'users':User.objects.filter(is_active=True).order_by('username'),'history':AreaResponsibilityHistory.objects.select_related('user','previous_user','changed_by')[:50]})
