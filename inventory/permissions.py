PERMISSION_CHOICES=[('orders.view','Ver Pedidos'),('orders.manage','Gestionar Pedidos'),('customers.manage','Gestionar Clientes'),('suppliers.manage','Gestionar Proveedores'),('components.manage','Gestionar Componentes'),('repairs.manage','Gestionar Reparaciones'),('components.reserve','Reservar Componentes'),('rma.manage','Gestionar RMA'),('procurement.view','Ver alertas de Compras'),('procurement.resolve','Resolver alertas de Compras'),('roles.manage','Gestionar roles y permisos')]

def user_is_manager(user):
 """Regla global: Gestor es el perfil funcional de maximo nivel y puede usar TODO."""
 if not getattr(user,'is_authenticated',False):return False
 if user.is_superuser:return True
 try:return user.pulsia_role_assignments.filter(role__active=True,role__code='gestor').exists()
 except Exception:return False

def user_has_permission(user,permission):
 if not getattr(user,'is_authenticated',False): return False
 if user_is_manager(user): return True
 return any(permission in (assignment.role.permissions or []) for assignment in user.pulsia_role_assignments.select_related('role').filter(role__active=True))

def user_is_purchasing(user):
 if not getattr(user,'is_authenticated',False): return False
 if user_is_manager(user): return True
 try:
  if user.area_responsibilities.filter(responsibility='purchasing').exists(): return True
 except Exception:
  pass
 return user.pulsia_role_assignments.filter(role__active=True,role__code='compras').exists()
