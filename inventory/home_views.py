from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import UserProfile
from .permissions import user_is_manager
from . import views


@login_required
def home(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if profile.is_guest:
        access_request = profile.user.access_upgrade_request if hasattr(profile.user, 'access_upgrade_request') else None
        return render(request, 'inventory/guest_dashboard.html', {'access_request': access_request, 'is_guest': True})
    return render(request, 'inventory/home.html', {
        'can_view_zone_stock': bool(request.user.is_staff or user_is_manager(request.user)),
    })


@login_required
def bodega_home(request):
    """Conserva el panel histórico de inventario bajo el área Bodega / Almacén."""
    query = request.GET.copy()
    query['view'] = 'inventory'
    request.GET = query
    return views.dashboard(request)
