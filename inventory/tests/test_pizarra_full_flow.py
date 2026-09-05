from django.contrib.auth import get_user_model
from django.test import TestCase

from inventory.models import ProductionZone
from inventory.order_models import CustomerOrder, OrderUnit, PhysicalUnit
from inventory.pallet_models import Pallet, PalletUnit
from inventory.unit_workflow_models import PhysicalUnitLocation, UnitIntervention


class PizarraFullFlowSimulationTests(TestCase):
    """Simulación integral del recorrido físico de una unidad por Mi Pizarra.

    Recorre todas las zonas productivas, verifica Fin, cambio de stock físico,
    Secadero, borrado de filas y el flujo especial Calidad -> Palet.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='sim_pizarra', password='test-only')
        cls.stock = CustomerOrder.objects.create(name='STOCK', customer=None, status='open', created_by=cls.user)
        expected = [
            (10, 'pintura', 'Pintura'),
            (15, 'secadero', 'Secadero'),
            (20, 'calidad', 'Calidad'),
            (30, 'montaje', 'Montaje'),
            (40, 'auditoria', 'Auditoría'),
            (50, 'garantias', 'Garantías'),
            (60, 'admision', 'Admisión'),
            (70, 'renove', 'Renove'),
            (80, 'reparaciones', 'Reparaciones'),
            (90, 'teclados', 'Teclados'),
            (100, 'direccion', 'Dirección'),
        ]
        cls.zones = []
        for position, code, name in expected:
            zone, _ = ProductionZone.objects.get_or_create(
                code=code,
                defaults={'name': name, 'position': position, 'is_active': True},
            )
            if zone.name != name or zone.position != position or not zone.is_active:
                zone.name = name
                zone.position = position
                zone.is_active = True
                zone.save(update_fields=['name', 'position', 'is_active'])
            cls.zones.append(zone)

    def setUp(self):
        self.client.force_login(self.user)

    def _start(self, sn, zone):
        response = self.client.post('/produccion/pizarra/anadir/', {
            'serial_number': sn,
            'origin_zone': zone.pk,
            'work_order': 'stock',
        })
        self.assertEqual(response.status_code, 302)
        physical = PhysicalUnit.objects.get(serial_number=sn)
        location = PhysicalUnitLocation.objects.select_related('zone', 'intervention').get(physical_unit=physical)
        self.assertEqual(location.zone_id, zone.pk)
        self.assertIsNone(location.intervention.finished_at)
        return location.intervention

    def _finish(self, intervention, destination):
        response = self.client.post(
            f'/produccion/intervencion/{intervention.pk}/terminar/',
            {'destination_zone': destination.pk},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertTrue(payload.get('ok'), payload)
        intervention.refresh_from_db()
        self.assertIsNotNone(intervention.finished_at)
        self.assertEqual(intervention.destination_zone_id, destination.pk)
        location = PhysicalUnitLocation.objects.select_related('zone').get(
            physical_unit=intervention.unit.physical_unit,
        )
        self.assertEqual(location.zone_id, destination.pk)
        return location

    def test_unit_can_cross_every_zone_and_finish_each_step(self):
        sn = 'SIM-ALL-ZONES-001'
        # Orden deliberado: sólo Pintura introduce en Secadero. Después la unidad
        # puede ser extraída de Secadero por cualquier zona al ficharla allí.
        route = self.zones + [self.zones[0]]
        for index in range(len(route) - 1):
            origin = route[index]
            destination = route[index + 1]
            intervention = self._start(sn, origin)
            self.assertEqual(intervention.zone_id, origin.pk)
            self._finish(intervention, destination)

        physical = PhysicalUnit.objects.get(serial_number=sn)
        self.assertEqual(physical.production_location.zone_id, self.zones[0].pk)
        self.assertEqual(
            UnitIntervention.objects.filter(unit__physical_unit=physical, finished_at__isnull=False).count(),
            len(route) - 1,
        )

    def test_only_paint_can_send_to_dryer(self):
        sn = 'SIM-DRYER-BLOCK-001'
        montage = ProductionZone.objects.get(code='montaje')
        dryer = ProductionZone.objects.get(code='secadero')
        intervention = self._start(sn, montage)
        response = self.client.post(
            f'/produccion/intervencion/{intervention.pk}/terminar/',
            {'destination_zone': dryer.pk},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json().get('ok'))
        intervention.refresh_from_db()
        self.assertIsNone(intervention.finished_at)
        self.assertEqual(intervention.unit.physical_unit.production_location.zone_id, montage.pk)

    def test_active_row_can_be_deleted_and_removes_current_location(self):
        sn = 'SIM-DELETE-001'
        montage = ProductionZone.objects.get(code='montaje')
        intervention = self._start(sn, montage)
        physical_id = intervention.unit.physical_unit_id
        response = self.client.post(
            f'/produccion/intervencion/{intervention.pk}/borrar/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json().get('ok'))
        self.assertTrue(response.json().get('removed_current_location'))
        self.assertFalse(UnitIntervention.objects.filter(pk=intervention.pk).exists())
        self.assertFalse(PhysicalUnitLocation.objects.filter(physical_unit_id=physical_id).exists())

    def test_quality_can_send_to_open_pallet_and_other_zone_can_extract(self):
        sn = 'SIM-PALLET-001'
        quality = ProductionZone.objects.get(code='calidad')
        repairs = ProductionZone.objects.get(code='reparaciones')
        intervention = self._start(sn, quality)

        # El flujo de palet usa la zona declarada en sesión además de la zona real
        # de la intervención.
        declare = self.client.post('/produccion/pizarra/zona-declarada/', {'zone_id': quality.pk})
        self.assertEqual(declare.status_code, 200)
        pallet = Pallet.objects.create(created_by=self.user)
        response = self.client.post(
            f'/pedidos/palets/intervencion/{intervention.pk}/anadir/',
            {'pallet_id': pallet.pk},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json().get('ok'))
        physical = PhysicalUnit.objects.get(serial_number=sn)
        self.assertFalse(PhysicalUnitLocation.objects.filter(physical_unit=physical).exists())
        self.assertTrue(PalletUnit.objects.filter(pallet=pallet, unit__physical_unit=physical).exists())

        # Cualquier zona puede extraer de un palet ABIERTO simplemente fichando
        # el SN en su Pizarra.
        extracted = self._start(sn, repairs)
        self.assertEqual(extracted.zone_id, repairs.pk)
        self.assertFalse(PalletUnit.objects.filter(pallet=pallet, unit__physical_unit=physical).exists())
        self.assertEqual(physical.production_location.zone_id, repairs.pk)
