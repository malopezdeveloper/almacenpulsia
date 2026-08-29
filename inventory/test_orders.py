from django.contrib.auth import get_user_model
from django.test import TestCase
from .order_models import Customer,Supplier,CustomerOrder,OrderUnit,Component,Repair,ComponentReservation,RMA,ProcurementAlert

class OrdersWorkflowTests(TestCase):
 def setUp(self):
  self.user=get_user_model().objects.create_superuser('gestor','gestor@example.invalid','test-pass')
  self.customer=Customer.objects.create(name='Cliente test')
  self.supplier=Supplier.objects.create(name='Proveedor test')
  self.order=CustomerOrder.objects.create(name='Pedido test',customer=self.customer,lot='L-1',created_by=self.user)
  self.unit=OrderUnit.objects.create(order=self.order,serial_number='SN-TEST-1',aiken_lot='L-1')
 def test_unit_can_have_many_repairs(self):
  Repair.objects.create(unit=self.unit,repair_type='Bateria',created_by=self.user)
  Repair.objects.create(unit=self.unit,repair_type='Teclado',created_by=self.user)
  self.assertEqual(self.unit.repairs.count(),2)
 def test_cancel_reservation_reactivates_component(self):
  component=Component.objects.create(component_type='Bateria',supplier=self.supplier,status='reserved')
  repair=Repair.objects.create(unit=self.unit,repair_type='Bateria',created_by=self.user)
  reservation=ComponentReservation.objects.create(repair=repair,component=component,technician=self.user,unit_serial_number=self.unit.serial_number)
  reservation.cancel(); component.refresh_from_db(); self.assertEqual(component.status,'active')
 def test_rma_requires_low_component(self):
  component=Component.objects.create(component_type='Bateria',supplier=self.supplier,status='active')
  rma=RMA(component=component,supplier=self.supplier,created_by=self.user)
  with self.assertRaises(Exception): rma.full_clean()
  component.status='low'; component.save(); rma.full_clean()
 def test_procurement_alert_belongs_to_repair(self):
  repair=Repair.objects.create(unit=self.unit,repair_type='Pantalla',created_by=self.user)
  alert=ProcurementAlert.objects.create(repair=repair,message='Sin pantalla disponible')
  self.assertEqual(alert.repair.unit.serial_number,'SN-TEST-1')
