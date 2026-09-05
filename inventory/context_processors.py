from .models import ChatMessage, InventoryTable, Reservation, Loan, LoanRequest, UserProfile, AccessUpgradeRequest, Incident, SecurityAccessEvent, BackupDiskConfig, ProductionZone
from .order_models import ProcurementAlert
from .permissions import user_is_purchasing,user_is_manager
from .storage_admin import request_storage_admin

def inventory_navigation(request):
    if not request.user.is_authenticated: return {}
    profile,_=UserProfile.objects.get_or_create(user=request.user); is_guest=profile.is_guest
    # Los catalogos de componentes pertenecen exclusivamente a Menu pedidos -> Componentes.
    # No deben convivir con las tablas normales del inventario en la navegacion global.
    navigation_tables = InventoryTable.objects.filter(active=True, component_catalog__isnull=True).order_by('position','name')
    context={'is_guest':is_guest,'is_manager_user':user_is_manager(request.user),'inventory_tables':InventoryTable.objects.none() if is_guest else navigation_tables,'unread_messages_count':ChatMessage.objects.filter(recipient=request.user,read_at__isnull=True).count(),'global_zones':ProductionZone.objects.filter(is_active=True).order_by('position','name'),'procurement_alert_count':0,'is_purchasing_user':user_is_purchasing(request.user)}
    if request.user.is_staff:
        try: context['security_red_count']=SecurityAccessEvent.objects.filter(reviewed=False,level='RED').count(); context['security_yellow_count']=SecurityAccessEvent.objects.filter(reviewed=False,level='YELLOW').count()
        except Exception: context['security_red_count']=0; context['security_yellow_count']=0
    if context['is_purchasing_user']:
        try: context['procurement_alert_count']=ProcurementAlert.objects.filter(status='open').count()
        except Exception: context['procurement_alert_count']=0
    if is_guest:
        context.update(active_loans_count=0,pending_reservations_count=0,unseen_reservations_count=0,pending_loan_requests_count=0); return context
    context['active_loans_count']=Loan.objects.filter(returned_at__isnull=True).count() if request.user.is_staff else Loan.objects.filter(borrower=request.user,returned_at__isnull=True).count()
    context['pending_reservations_count']=Reservation.objects.filter(status='pending').count() if request.user.is_staff else 0; context['unseen_reservations_count']=context['pending_reservations_count']; context['pending_loan_requests_count']=LoanRequest.objects.filter(status='pending').count() if request.user.is_staff else 0; context['pending_incidents_count']=Incident.objects.filter(status='pending').count() if request.user.is_staff else 0
    if request.user.is_superuser:
        context['password_reset_requests_count']=UserProfile.objects.filter(password_reset_requested_at__isnull=False).count(); context['pending_access_upgrade_count']=AccessUpgradeRequest.objects.filter(status='pending').count(); context['backup_disk_alert']=0
        try:
            cfg=BackupDiskConfig.objects.first()
            if cfg and (cfg.uuid or (cfg.mode=='local' and cfg.local_path)):
                st=request_storage_admin({'action':'status_backup_mount','uuid':cfg.uuid},timeout=0.8); context['backup_disk_alert']=0 if ((cfg.mode=='local' or (st.get('present') and st.get('matches'))) and st.get('continuous',{}).get('state')=='ok') else 1
        except Exception: context['backup_disk_alert']=1
    return context
