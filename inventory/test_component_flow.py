from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import UserProfile
from .order_models import Customer, CustomerOrder, OrderUnit, ComponentType, Component, PhysicalUnit, ComponentReservation
from .component_flow_models import OrderComponentAuthorization, ComponentIncreaseRequest, ReservationAllocation


class ComponentReservationFlowTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='flow_user', password='clave123', is_staff=True)
        UserProfile.objects.create(user=self.user)
        self.customer = Customer.objects.create(name='Cliente flow')
        self.order = CustomerOrder.objects.create(name='PEDIDO FLOW', customer=self.customer, created_by=self.user)
        self.physical = PhysicalUnit.objects.create(serial_number='SN-FLOW-001')
        self.unit = OrderUnit.objects.create(order=self.order, physical_unit=self.physical, serial_number=self.physical.serial_number)
        self.kind = ComponentType.objects.create(name='Batería flow', created_by=self.user)
        self.component = Component.objects.create(component_kind=self.kind, component_type=self.kind.name, reference='BAT-FLOW-001')
        self.client.login(username='flow_user', password='clave123')

    def test_unit_opens_two_source_reservation_screen(self):
        response = self.client.get(reverse('reservation_source', kwargs={'unit_pk': self.unit.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'BODEGA')
        self.assertContains(response, 'COMPONENTES')

    def test_warehouse_reservation_needs_no_order_authorization(self):
        response = self.client.post(reverse('reserve_physical_component', kwargs={
            'unit_pk': self.unit.pk, 'source': 'warehouse', 'component_pk': self.component.pk,
        }))
        self.assertRedirects(response, reverse('unit_detail', kwargs={'pk': self.unit.pk}))
        reservation = ComponentReservation.objects.get(component=self.component)
        allocation = ReservationAllocation.objects.get(reservation=reservation)
        self.assertEqual(allocation.order, self.order)
        self.assertEqual(allocation.source, 'warehouse')
        self.assertIsNone(allocation.authorization)
        self.component.refresh_from_db()
        self.assertEqual(self.component.status, 'reserved')

    def test_exhausted_order_limit_creates_request_not_reservation(self):
        OrderComponentAuthorization.objects.create(order=self.order, component_type=self.kind, approved_quantity=0, updated_by=self.user)
        response = self.client.post(reverse('request_component_increase', kwargs={'unit_pk': self.unit.pk}), {
            'component_type': self.kind.pk, 'quantity': 2,
        })
        self.assertRedirects(response, reverse('order_components', kwargs={'unit_pk': self.unit.pk}))
        request = ComponentIncreaseRequest.objects.get(unit=self.unit)
        self.assertEqual(request.status, 'pending')
        self.assertEqual(request.requested_quantity, 2)
        self.assertFalse(ComponentReservation.objects.exists())

    def test_approval_increases_limit_but_does_not_reserve_physical_stock(self):
        request = ComponentIncreaseRequest.objects.create(
            order=self.order, unit=self.unit, component_type=self.kind,
            requested_quantity=3, requested_by=self.user,
        )
        response = self.client.post(reverse('resolve_component_increase', kwargs={'request_pk': request.pk, 'action': 'approve'}))
        self.assertRedirects(response, reverse('order_components', kwargs={'unit_pk': self.unit.pk}))
        request.refresh_from_db()
        auth = OrderComponentAuthorization.objects.get(order=self.order, component_type=self.kind)
        self.assertEqual(request.status, 'approved')
        self.assertEqual(auth.approved_quantity, 3)
        self.assertFalse(ComponentReservation.objects.exists())

    def test_stock_order_is_unlimited_but_still_requires_physical_component(self):
        stock = CustomerOrder.objects.create(name='STOCK', customer=self.customer, created_by=self.user)
        physical = PhysicalUnit.objects.create(serial_number='SN-STOCK-001')
        unit = OrderUnit.objects.create(order=stock, physical_unit=physical, serial_number=physical.serial_number)
        response = self.client.get(reverse('order_components', kwargs={'unit_pk': unit.pk}))
        self.assertEqual(response.status_code, 200)
        auth = OrderComponentAuthorization.objects.get(order=stock, component_type=self.kind)
        self.assertTrue(auth.unlimited)
        self.assertFalse(ComponentReservation.objects.filter(unit=unit).exists())

    def test_closed_order_cannot_reserve(self):
        self.order.status = 'closed'
        self.order.save(update_fields=['status'])
        response = self.client.get(reverse('reservation_source', kwargs={'unit_pk': self.unit.pk}))
        self.assertRedirects(response, reverse('unit_detail', kwargs={'pk': self.unit.pk}))
        self.assertFalse(ComponentReservation.objects.exists())
