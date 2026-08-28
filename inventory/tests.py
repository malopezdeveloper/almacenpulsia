from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch
from types import SimpleNamespace

from .models import AccessUpgradeRequest, ChatMessage, InventoryRecord, InventoryTable, IPBan, Loan, LoanItem, LoanRequest, Reservation, UserProfile


class PasswordRecoveryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.gestor = User.objects.create_superuser(username="gestor_test", password="gestor123", email="")
        self.user = User.objects.create_user(username="tecnico", password="clave123")
        UserProfile.objects.create(user=self.user)

    def test_user_can_request_and_gestor_can_authorize_password_reset(self):
        response = self.client.post(reverse("login"), {"action": "request_reset", "username": "tecnico"})
        self.assertRedirects(response, reverse("login"))
        profile = UserProfile.objects.get(user=self.user)
        self.assertIsNotNone(profile.password_reset_requested_at)

        self.client.login(username="gestor_test", password="gestor123")
        response = self.client.post(reverse("users_panel"), {"action": "reset", "user_id": self.user.pk})
        self.assertRedirects(response, reverse("users_panel"))
        self.user.refresh_from_db(); profile.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())
        self.assertIsNotNone(profile.password_reset_authorized_at)

    def test_authorized_user_sets_own_new_password(self):
        profile = self.user.inventory_profile
        self.user.set_unusable_password(); self.user.save(update_fields=["password"])
        profile.password_reset_authorized_at = timezone.now(); profile.save()
        response = self.client.post(reverse("login"), {
            "action": "set_reset_password", "username": "tecnico",
            "password": "nueva123", "password_confirm": "nueva123",
        })
        self.assertRedirects(response, reverse("dashboard"))
        self.user.refresh_from_db(); profile.refresh_from_db()
        self.assertTrue(self.user.check_password("nueva123"))
        self.assertIsNone(profile.password_reset_authorized_at)


class LoanTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="admin", password="admin123", is_staff=True)
        self.borrower = User.objects.create_user(username="usuario", password="user123")
        UserProfile.objects.create(user=self.admin); UserProfile.objects.create(user=self.borrower)
        self.item = LoanItem.objects.create(internal_id="PREST-001", name="Portátil de sustitución", category="Portátiles", created_by=self.admin)

    def test_user_requests_admin_accepts_and_return_makes_item_available(self):
        self.client.login(username="usuario", password="user123")
        response = self.client.post(reverse("loans_center"), {"action": "request", "item": self.item.pk, "notes": "Necesario para reparación"})
        self.assertRedirects(response, reverse("loans_center") + "?tab=search")
        req = LoanRequest.objects.get(item=self.item)
        self.item.refresh_from_db()
        self.assertEqual(req.status, "pending")
        self.assertEqual(self.item.status, "pending")

        self.client.logout(); self.client.login(username="admin", password="admin123")
        response = self.client.post(reverse("loans_center"), {"action": "accept_request", "request_id": req.pk})
        self.assertRedirects(response, reverse("loans_center") + "?tab=pending")
        req.refresh_from_db(); self.item.refresh_from_db(); loan = Loan.objects.get(request=req)
        self.assertEqual(req.status, "accepted")
        self.assertEqual(self.item.status, "loaned")
        self.assertEqual(loan.borrower, self.borrower)

        response = self.client.post(reverse("loans_center"), {"action": "return", "loan_id": loan.pk})
        self.assertRedirects(response, reverse("loans_center") + "?tab=search")
        self.item.refresh_from_db(); loan.refresh_from_db()
        self.assertEqual(self.item.status, "available")
        self.assertIsNotNone(loan.returned_at)

    def test_admin_can_create_internal_loan_item(self):
        self.client.login(username="admin", password="admin123")
        response = self.client.post(reverse("loans_center"), {
            "action": "create_item", "name": "Tester", "category": "Herramientas",
            "brand": "", "model_reference": "", "serial_number": "", "description": "", "notes": "",
        })
        self.assertRedirects(response, reverse("loans_center") + "?tab=items")
        item = LoanItem.objects.get(name="Tester")
        self.assertRegex(item.internal_id, r"^PREST-\d{6}$")


class ReservationHistoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.gestor = User.objects.create_superuser(username="gestor", password="gestor123", email="")
        UserProfile.objects.create(user=self.gestor)
        self.table = InventoryTable.objects.create(name="RAM", slug="ram", id_header="ID", id_prefix="RAM-", created_by=self.gestor)
        self.record = InventoryRecord.objects.create(table=self.table, internal_id="RAM-0001", created_by=self.gestor, data={"marca": "Kingston"})
        self.reservation = Reservation.objects.create(record=self.record, requested_by=self.gestor, destination="Reparaciones", destination_sn="SN-XYZ", status="delivered", resolved_by=self.gestor, resolved_at=timezone.now())

    def test_delivered_reservation_remains_searchable(self):
        self.client.login(username="gestor", password="gestor123")
        response = self.client.get(reverse("reservations_center"), {"delivered_only": "1", "sn": "XYZ"})
        self.assertContains(response, "RAM-0001")
        self.assertContains(response, "Objeto entregado")


class RequestWorkflowAndAlertTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="admin_alert", password="admin123", is_staff=True)
        self.user = User.objects.create_user(username="user_alert", password="user123")
        UserProfile.objects.create(user=self.admin); UserProfile.objects.create(user=self.user)
        self.table = InventoryTable.objects.create(name="Pantallas", slug="pantallas", id_header="ID", id_prefix="PAN-", created_by=self.admin)
        self.record = InventoryRecord.objects.create(table=self.table, internal_id="PAN-0001", created_by=self.admin)

    def test_normal_user_requests_reservation_and_admin_accepts(self):
        self.client.login(username="user_alert", password="user123")
        response = self.client.post(reverse("reserve_record", kwargs={"pk": self.record.pk}), {"destination": "Reparaciones", "destination_sn": "SN-DEST-01"})
        self.assertEqual(response.status_code, 302)
        reservation = Reservation.objects.get(record=self.record)
        self.record.refresh_from_db()
        self.assertEqual(reservation.status, "pending")
        self.assertEqual(self.record.status, "available")

        self.client.logout(); self.client.login(username="admin_alert", password="admin123")
        response = self.client.post(reverse("reservations_center"), {"action": "accept", "reservation_id": reservation.pk})
        self.assertRedirects(response, reverse("reservations_center") + "?tab=pending")
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, "accepted")
        self.assertEqual(reservation.accepted_by, self.admin)
        self.assertIsNotNone(reservation.accepted_at)

    def test_notification_status_counts_three_pending_menus(self):
        Reservation.objects.create(record=self.record, requested_by=self.user, destination="Reparaciones", destination_sn="SN-1")
        item = LoanItem.objects.create(internal_id="PREST-A", name="Adaptador", created_by=self.admin, status="pending")
        LoanRequest.objects.create(item=item, requested_by=self.user)
        ChatMessage.objects.create(sender=self.user, recipient=self.admin, body="Mensaje pendiente")
        self.client.login(username="admin_alert", password="admin123")
        data = self.client.get(reverse("notification_status")).json()
        self.assertEqual(data["pending_reservations"], 1)
        self.assertEqual(data["pending_loan_requests"], 1)
        self.assertEqual(data["unread_messages"], 1)


class GestorBootstrapTests(TestCase):
    def test_bootstrap_logs_in_gestor_once_and_allows_setting_password(self):
        import tempfile
        from django.core.management import call_command
        User = get_user_model()
        gestor = User.objects.create_superuser(username="gestor_boot", password="anterior123", email="")
        UserProfile.objects.create(user=gestor)
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            token_path = fh.name
        call_command("preparar_acceso_gestor", token_file=token_path, minutes=15)
        gestor.refresh_from_db()
        self.assertFalse(gestor.has_usable_password())
        token = open(token_path, encoding="utf-8").read().strip()
        response = self.client.get(reverse("gestor_bootstrap_login", kwargs={"token": token}))
        self.assertRedirects(response, reverse("users_panel"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), gestor.pk)
        # El mismo token queda consumido.
        self.client.logout()
        response = self.client.get(reverse("gestor_bootstrap_login", kwargs={"token": token}))
        self.assertEqual(response.status_code, 403)
        # Una nueva preparación permite entrar y establecer la contraseña desde Usuarios.
        call_command("preparar_acceso_gestor", token_file=token_path, minutes=15)
        token2 = open(token_path, encoding="utf-8").read().strip()
        self.client.get(reverse("gestor_bootstrap_login", kwargs={"token": token2}))
        response = self.client.post(reverse("users_panel"), {"action": "set_own_password", "password": "nuevaGestor123", "password_confirm": "nuevaGestor123"})
        self.assertRedirects(response, reverse("users_panel"))
        gestor.refresh_from_db()
        self.assertTrue(gestor.check_password("nuevaGestor123"))


class WorkflowTemplateSmokeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="smoke_admin", password="admin123", is_staff=True)
        self.user = User.objects.create_user(username="smoke_user", password="user123")
        UserProfile.objects.create(user=self.admin); UserProfile.objects.create(user=self.user)
        self.item = LoanItem.objects.create(internal_id="SMK-001", name="Portátil", created_by=self.admin)

    def test_staff_tabs_render(self):
        self.client.login(username="smoke_admin", password="admin123")
        for url in [
            reverse("loans_center") + "?tab=search",
            reverse("loans_center") + "?tab=pending",
            reverse("loans_center") + "?tab=items",
            reverse("reservations_center") + "?tab=search",
            reverse("reservations_center") + "?tab=pending",
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)

    def test_normal_user_can_render_request_centers(self):
        self.client.login(username="smoke_user", password="user123")
        self.assertEqual(self.client.get(reverse("loans_center")).status_code, 200)
        self.assertEqual(self.client.get(reverse("reservations_center")).status_code, 200)

class ProductivityReportTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="prod_admin", password="admin123", is_staff=True)
        self.worker = User.objects.create_user(username="prod_worker", password="worker123", is_staff=True)
        UserProfile.objects.create(user=self.admin); UserProfile.objects.create(user=self.worker)
        self.table = InventoryTable.objects.create(name="Prod", slug="prod", id_header="ID", id_prefix="P-", created_by=self.admin)
        InventoryRecord.objects.create(table=self.table, internal_id="P-001", created_by=self.worker)
        InventoryRecord.objects.create(table=self.table, internal_id="P-002", created_by=self.worker)

    def test_staff_can_see_productivity_by_user(self):
        self.client.login(username="prod_admin", password="admin123")
        response = self.client.get(reverse("productivity_report"), {"preset": "today", "user": self.worker.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "prod_worker")
        self.assertContains(response, "P-001")
        self.assertEqual(response.context["total_period"], 2)

    def test_normal_user_cannot_see_productivity(self):
        normal = get_user_model().objects.create_user(username="prod_normal", password="normal123")
        UserProfile.objects.create(user=normal)
        self.client.login(username="prod_normal", password="normal123")
        self.assertEqual(self.client.get(reverse("productivity_report")).status_code, 403)


class ClientBatchTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="batch_admin", password="admin123", is_staff=True)
        self.normal = User.objects.create_user(username="batch_normal", password="normal123")
        UserProfile.objects.create(user=self.admin); UserProfile.objects.create(user=self.normal)
        from .models import ClientBatchSheet, ClientBatchRow
        self.sheet = ClientBatchSheet.objects.create(name="Lote HP agosto", client="HP", concept="Plan Renove", created_by=self.admin)
        self.row = ClientBatchRow.objects.create(sheet=self.sheet, internal_id="HP-001", reference="REF-A", units_pending=70, units_stock=30, units_sent=0, unit_price="15.50", total_price="1550.00", client="HP", created_by=self.admin, updated_by=self.admin)

    def test_stock_increase_reduces_pending_and_recalculates_total(self):
        from .models import ClientBatchChange
        self.client.login(username="batch_admin", password="admin123")
        response = self.client.post(reverse("client_batches_sheet", kwargs={"sheet_id": self.sheet.pk}), {"action":"update_cell","row_id":self.row.pk,"field":"units_stock","value":"40"})
        self.assertRedirects(response, reverse("client_batches_sheet", kwargs={"sheet_id": self.sheet.pk}))
        self.row.refresh_from_db()
        self.assertEqual(self.row.units_pending, 60)
        self.assertEqual(self.row.units_stock, 40)
        self.assertEqual(str(self.row.total_price), "1550.00")
        self.assertTrue(ClientBatchChange.objects.filter(row=self.row, action="row_modified").exists())

    def test_sent_increase_reduces_stock(self):
        self.client.login(username="batch_admin", password="admin123")
        self.client.post(reverse("client_batches_sheet", kwargs={"sheet_id": self.sheet.pk}), {"action":"update_cell","row_id":self.row.pk,"field":"units_sent","value":"12"})
        self.row.refresh_from_db()
        self.assertEqual(self.row.units_sent, 12)
        self.assertEqual(self.row.units_stock, 18)
        self.assertEqual(self.row.units_pending, 70)
        self.assertEqual(str(self.row.total_price), "1550.00")

    def test_cannot_send_more_than_stock(self):
        self.client.login(username="batch_admin", password="admin123")
        self.client.post(reverse("client_batches_sheet", kwargs={"sheet_id": self.sheet.pk}), {"action":"update_cell","row_id":self.row.pk,"field":"units_sent","value":"50"})
        self.row.refresh_from_db()
        self.assertEqual(self.row.units_sent, 0)
        self.assertEqual(self.row.units_stock, 30)

    def test_staff_can_render_internal_batch_sheet(self):
        from .models import ClientBatchField
        field = ClientBatchField.objects.create(sheet=self.sheet, name="Ubicación", key="ubicacion", created_by=self.admin)
        self.row.extra_data = {"ubicacion": "Estantería A"}; self.row.save(update_fields=["extra_data","updated_at"])
        self.client.login(username="batch_admin", password="admin123")
        response = self.client.get(reverse("client_batches_sheet", kwargs={"sheet_id": self.sheet.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lote HP agosto")
        self.assertContains(response, "HP-001")
        self.assertContains(response, "Estantería A")

    def test_normal_user_cannot_access_internal_batches(self):
        self.client.login(username="batch_normal", password="normal123")
        self.assertEqual(self.client.get(reverse("client_batches")).status_code, 403)

class AccessControlTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.gestor = User.objects.create_superuser(username="access_gestor", password="gestor123", email="")
        self.admin = User.objects.create_user(username="access_admin", password="admin123", is_staff=True)
        UserProfile.objects.create(user=self.gestor); UserProfile.objects.create(user=self.admin)

    def test_only_gestor_can_open_access_control(self):
        self.client.login(username="access_admin", password="admin123")
        self.assertEqual(self.client.get(reverse("access_control")).status_code, 403)
        self.client.logout(); self.client.login(username="access_gestor", password="gestor123")
        self.assertEqual(self.client.get(reverse("access_control")).status_code, 200)

    def test_gestor_can_ban_and_unban_other_ip(self):
        from .models import IPBan, ServiceAccess
        self.client.login(username="access_gestor", password="gestor123")
        ServiceAccess.objects.create(ip_address="192.168.1.55", user=self.admin, last_path="/")
        response = self.client.post(reverse("access_control"), {"action":"ban","ip_address":"192.168.1.55","minutes":"15","reason":"Prueba"})
        self.assertRedirects(response, reverse("access_control"))
        self.assertTrue(IPBan.objects.filter(ip_address="192.168.1.55", revoked_at__isnull=True).exists())
        self.client.post(reverse("access_control"), {"action":"unban","ip_address":"192.168.1.55"})
        self.assertFalse(IPBan.objects.filter(ip_address="192.168.1.55", revoked_at__isnull=True, banned_until__gt=timezone.now()).exists())


    def test_gestor_can_create_permanent_ban_and_unban_it(self):
        from .models import IPBan, ServiceAccess
        self.client.login(username="access_gestor", password="gestor123")
        ServiceAccess.objects.create(ip_address="192.168.1.77", user=self.admin, last_path="/")
        response = self.client.post(reverse("access_control"), {"action":"ban","ip_address":"192.168.1.77","minutes":"permanent","reason":"Bloqueo permanente"})
        self.assertRedirects(response, reverse("access_control"))
        ban = IPBan.objects.get(ip_address="192.168.1.77", revoked_at__isnull=True)
        self.assertIsNone(ban.banned_until)
        self.assertTrue(ban.is_active)
        self.client.post(reverse("access_control"), {"action":"unban","ip_address":"192.168.1.77"})
        ban.refresh_from_db()
        self.assertIsNotNone(ban.revoked_at)

    def test_middleware_blocks_permanent_ban(self):
        from .models import IPBan
        IPBan.objects.create(ip_address="192.168.1.88", banned_by=self.gestor, banned_until=None)
        response = self.client.get("/", REMOTE_ADDR="192.168.1.88")
        self.assertEqual(response.status_code, 403)
        self.assertIn("permanentemente", response.content.decode("utf-8").lower())
    def test_middleware_blocks_banned_ip(self):
        from .models import IPBan
        IPBan.objects.create(ip_address="192.168.1.60", banned_by=self.gestor, banned_until=timezone.now()+timezone.timedelta(minutes=30))
        response=self.client.get(reverse("login"), REMOTE_ADDR="192.168.1.60")
        self.assertEqual(response.status_code, 403)

    def test_gestor_can_request_current_server_ip_reservation(self):
        self.client.login(username="access_gestor", password="gestor123")
        fake=SimpleNamespace(status="applied",ip_address="192.168.50.20",message="OK")
        with patch("inventory.views.request_current_ip_reservation", return_value=fake) as request_reservation:
            response=self.client.post(reverse("access_control"), {"action":"reserve_server_ip"})
        self.assertRedirects(response, reverse("access_control"))
        request_reservation.assert_called_once_with(self.gestor)

    def test_admin_cannot_request_network_reservation(self):
        self.client.login(username="access_admin", password="admin123")
        response=self.client.post(reverse("access_control"), {"action":"reserve_server_ip"})
        self.assertEqual(response.status_code,403)


class ClientBatchNewFieldsTests(TestCase):
    def setUp(self):
        User=get_user_model(); self.admin=User.objects.create_user(username="batch2_admin",password="admin123",is_staff=True); UserProfile.objects.create(user=self.admin)
        from .models import ClientBatchSheet
        self.sheet=ClientBatchSheet.objects.create(name="PED-001",client="Proveedor X",concept="Cliente Y",created_by=self.admin)

    def test_new_row_gets_incremental_id_and_new_fields(self):
        from .models import ClientBatchRow
        self.client.login(username="batch2_admin",password="admin123")
        response=self.client.post(reverse("client_batches_sheet",kwargs={"sheet_id":self.sheet.pk}),{
            "action":"create_row","row-brand":"HP","row-model_reference":"EliteBook","row-component":"Pantalla","row-reference":"REF-1",
            "row-units_pending":"10","row-units_stock":"0","row-units_sent":"0","row-unit_price":"12.50","row-client":"Cliente Y","row-observations":"Sin daños"
        })
        self.assertRedirects(response,reverse("client_batches_sheet",kwargs={"sheet_id":self.sheet.pk}))
        row=ClientBatchRow.objects.get(sheet=self.sheet)
        self.assertEqual(row.internal_id,"1"); self.assertEqual(row.brand,"HP"); self.assertEqual(row.component,"Pantalla"); self.assertEqual(row.observations,"Sin daños")
        self.sheet.refresh_from_db(); self.assertEqual(self.sheet.next_row_number,2)

    def test_labels_are_renamed(self):
        self.client.login(username="batch2_admin",password="admin123")
        response=self.client.get(reverse("client_batches_sheet",kwargs={"sheet_id":self.sheet.pk})+"?tab=sheets")
        self.assertContains(response,"Pedido"); self.assertContains(response,"Proveedor"); self.assertContains(response,"Cliente")


class ChatKeyboardTemplateTests(TestCase):
    def test_chat_template_contains_enter_to_send_logic(self):
        User=get_user_model(); a=User.objects.create_user(username="chat_a",password="a12345"); b=User.objects.create_user(username="chat_b",password="b12345")
        UserProfile.objects.create(user=a); UserProfile.objects.create(user=b)
        self.client.login(username="chat_a",password="a12345")
        response=self.client.get(reverse("chat_conversation",kwargs={"user_id":b.pk}))
        self.assertContains(response,"e.key==='Enter'")
        self.assertContains(response,"!e.shiftKey")

class AutomaticIdAndDuplicateIncidentTests(TestCase):
    def setUp(self):
        from .models import InventoryField
        User = get_user_model()
        self.admin = User.objects.create_user(username="id_admin", password="admin123", is_staff=True)
        UserProfile.objects.create(user=self.admin)
        self.table = InventoryTable.objects.create(name="Baterias", slug="baterias", id_header="ID", id_prefix="BAT-", id_width=4, next_number=2, created_by=self.admin)
        InventoryField.objects.create(table=self.table, name="ID", key="id", position=0, is_primary=True)
        InventoryField.objects.create(table=self.table, name="Marca", key="marca", position=1)
        InventoryField.objects.create(table=self.table, name="Modelo", key="modelo", position=2)
        self.original = InventoryRecord.objects.create(table=self.table, internal_id="BAT-0001", data={"marca":"Dell","modelo":"A"}, created_by=self.admin)

    def test_creation_forms_do_not_expose_generated_ids(self):
        from .forms import DynamicRecordForm, LoanItemForm, InventoryTableForm
        record_form = DynamicRecordForm(self.table)
        self.assertNotIn("internal_id", record_form.fields)
        self.assertNotIn("existing_id", record_form.fields)
        self.assertNotIn("internal_id", LoanItemForm().fields)
        self.assertEqual(list(InventoryTableForm().fields), ["name"])

    def test_duplicate_incident_is_resolved_one_by_one_with_new_generated_id(self):
        from .models import Incident, LabelPrintJob
        incident = Incident.objects.create(
            title="ID duplicado en Baterias: BAT-0001",
            details="Registro aislado",
            kind="duplicate_id",
            severity="error",
            source_file="Inventario_Piezas.xlsx",
            source_sheet="Baterias",
            source_row=7,
            payload={"ID":"BAT-0001","Marca":"HP","Modelo":"B","__duplicate_internal_id":"BAT-0001","__inventory_table_pk":self.table.pk},
        )
        self.client.login(username="id_admin", password="admin123")
        response = self.client.post(reverse("incidents"), {"incident_id":incident.pk,"action":"resolve_duplicate"})
        self.assertRedirects(response, reverse("incidents"))
        incident.refresh_from_db()
        self.assertEqual(incident.status, "resolved")
        new_id = incident.payload["resolution"]["new_id"]
        self.assertNotEqual(new_id, "BAT-0001")
        created = InventoryRecord.objects.get(internal_id=new_id)
        self.assertEqual(created.data["marca"], "HP")
        self.assertEqual(created.data["modelo"], "B")
        self.assertEqual(created.status, "available")
        self.assertTrue(LabelPrintJob.objects.filter(identifier=new_id, copies=2).exists())

    def test_loan_item_id_is_generated_without_posted_id(self):
        self.client.login(username="id_admin", password="admin123")
        response = self.client.post(reverse("loans_center"), {
            "action":"create_item", "name":"Tester", "category":"Herramientas", "brand":"Fluke",
            "model_reference":"", "serial_number":"", "description":"", "notes":"",
        })
        self.assertRedirects(response, reverse("loans_center") + "?tab=items")
        item = LoanItem.objects.get(name="Tester")
        self.assertRegex(item.internal_id, r"^PREST-\d{6}$")

class LabelSequencePrintingTests(TestCase):
    def setUp(self):
        User=get_user_model()
        self.admin=User.objects.create_user(username="print_admin",password="admin123",is_staff=True)
        UserProfile.objects.create(user=self.admin)

    def test_sequence_form_increments_only_trailing_number(self):
        from .forms import LabelSequenceForm
        form=LabelSequenceForm({
            "start_id":"RAM-0098",
            "end_id":"RAM-0101",
            "copies":"2",
            "confirm":"on",
        })
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.identifiers(),["RAM-0098","RAM-0099","RAM-0100","RAM-0101"])
        self.assertEqual(form.cleaned_data["copies_int"],2)

    def test_sequence_form_rejects_different_prefixes(self):
        from .forms import LabelSequenceForm
        form=LabelSequenceForm({"start_id":"RAM-0001","end_id":"BAT-0002","copies":"1","confirm":"on"})
        self.assertFalse(form.is_valid())
        self.assertIn("end_id",form.errors)

    def test_sequence_printing_creates_jobs_without_inventory_records(self):
        from .models import LabelPrintJob, InventoryRecord
        before=InventoryRecord.objects.count()
        self.client.login(username="print_admin",password="admin123")
        response=self.client.post(reverse("printing_center"),{
            "action":"sequence",
            "sequence-start_id":"LOT-0001",
            "sequence-end_id":"LOT-0003",
            "sequence-copies":"1",
            "sequence-confirm":"on",
        })
        self.assertRedirects(response,reverse("printing_center"))
        self.assertEqual(InventoryRecord.objects.count(),before)
        jobs=list(LabelPrintJob.objects.filter(identifier__startswith="LOT-").order_by("identifier"))
        self.assertEqual([j.identifier for j in jobs],["LOT-0001","LOT-0002","LOT-0003"])
        self.assertTrue(all(j.copies==1 for j in jobs))

class GuestAccessWorkflowTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.gestor = User.objects.create_superuser(username="guest_gestor", password="gestor123", email="")
        UserProfile.objects.create(user=self.gestor, role="user")
        self.other = User.objects.create_user(username="chat_user", password="chat123")
        UserProfile.objects.create(user=self.other, role="user")

    def create_guest(self, username="invitado", ip="192.168.10.55"):
        User = get_user_model()
        guest = User.objects.create_user(username=username, password="guest123")
        UserProfile.objects.create(user=guest, role="guest", created_ip=ip)
        return guest

    def test_guest_only_sees_guest_dashboard_and_chat(self):
        guest = self.create_guest()
        self.client.login(username=guest.username, password="guest123")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Acceso de invitado")
        self.assertContains(response, "Solicitar acceso como Usuario")
        self.assertNotContains(response, "Préstamos")
        self.assertEqual(self.client.get(reverse("chat_center")).status_code, 200)
        # Intentar acceder directamente a inventario se redirige al dashboard.
        response = self.client.get(reverse("raw_table"))
        self.assertRedirects(response, reverse("dashboard"))

    def test_guest_can_request_upgrade_once(self):
        guest = self.create_guest()
        self.client.login(username=guest.username, password="guest123")
        response = self.client.post(reverse("request_access_upgrade"), REMOTE_ADDR="192.168.10.55")
        self.assertRedirects(response, reverse("dashboard"))
        req = AccessUpgradeRequest.objects.get(user=guest)
        self.assertEqual(req.status, "pending")
        self.assertEqual(req.requested_ip, "192.168.10.55")
        self.client.post(reverse("request_access_upgrade"), REMOTE_ADDR="192.168.10.55")
        self.assertEqual(AccessUpgradeRequest.objects.filter(user=guest).count(), 1)

    def test_gestor_approves_guest_and_promotes_to_user(self):
        guest = self.create_guest()
        req = AccessUpgradeRequest.objects.create(user=guest, requested_ip="192.168.10.56")
        self.client.login(username=self.gestor.username, password="gestor123")
        response = self.client.post(reverse("users_panel"), {
            "action": "approve_guest",
            "user_id": guest.pk,
        })
        self.assertRedirects(response, reverse("users_panel"))
        guest.refresh_from_db()
        guest.inventory_profile.refresh_from_db()
        req.refresh_from_db()
        self.assertEqual(guest.inventory_profile.role, "user")
        self.assertEqual(req.status, "approved")
        self.assertEqual(req.decided_by, self.gestor)
        self.assertTrue(guest.is_active)

    def test_gestor_denies_guest_blocks_account_and_ip_permanently(self):
        guest = self.create_guest(ip="192.168.10.57")
        req = AccessUpgradeRequest.objects.create(user=guest, requested_ip="192.168.10.57")
        self.client.login(username=self.gestor.username, password="gestor123")
        response = self.client.post(
            reverse("users_panel"),
            {"action": "deny_guest", "user_id": guest.pk},
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertRedirects(response, reverse("users_panel"))
        guest.refresh_from_db()
        req.refresh_from_db()
        self.assertFalse(guest.is_active)
        self.assertEqual(req.status, "denied")
        ban = IPBan.objects.get(ip_address="192.168.10.57", revoked_at__isnull=True)
        self.assertIsNone(ban.banned_until)

    def test_self_registration_creates_guest(self):
        response = self.client.post(reverse("login"), {
            "username": "nuevo_invitado",
            "password": "clave123",
        }, REMOTE_ADDR="192.168.10.58")
        self.assertRedirects(response, reverse("dashboard"))
        user = get_user_model().objects.get(username="nuevo_invitado")
        self.assertEqual(user.inventory_profile.role, "guest")

class ReservationDeliveryWorkflowV30Tests(TestCase):
    def setUp(self):
        User=get_user_model()
        self.admin=User.objects.create_user(username="resv30_admin",password="admin123",is_staff=True)
        self.user=User.objects.create_user(username="resv30_user",password="user123")
        UserProfile.objects.create(user=self.admin); UserProfile.objects.create(user=self.user)
        self.table=InventoryTable.objects.create(name="RAM V30",slug="ram-v30",id_header="ID",id_prefix="RV-",created_by=self.admin)
        self.record=InventoryRecord.objects.create(table=self.table,internal_id="RV-001",created_by=self.admin,status="available")

    def test_request_and_approval_do_not_change_object_status_until_delivery(self):
        self.client.login(username="resv30_user",password="user123")
        self.client.post(reverse("reserve_record",kwargs={"pk":self.record.pk}),{"destination":"Reparaciones","destination_sn":"DEST-1"})
        req=Reservation.objects.get(record=self.record)
        self.record.refresh_from_db()
        self.assertEqual(req.status,"pending")
        self.assertEqual(self.record.status,"available")
        self.client.logout(); self.client.login(username="resv30_admin",password="admin123")
        self.client.post(reverse("reservations_center"),{"action":"accept","reservation_id":req.pk})
        req.refresh_from_db(); self.record.refresh_from_db()
        self.assertEqual(req.status,"accepted")
        self.assertEqual(self.record.status,"available")
        self.client.logout(); self.client.login(username="resv30_user",password="user123")
        self.client.post(reverse("reservations_center"),{"action":"deliver","reservation_id":req.pk})
        req.refresh_from_db(); self.record.refresh_from_db()
        self.assertEqual(req.status,"delivered")
        self.assertEqual(self.record.status,"assigned")

    def test_admin_can_approve_and_deliver_in_one_action(self):
        Reservation.objects.create(record=self.record,requested_by=self.user,destination="Montaje",destination_sn="DEST-2")
        req=Reservation.objects.get(record=self.record)
        self.client.login(username="resv30_admin",password="admin123")
        self.client.post(reverse("reservations_center"),{"action":"approve_deliver","reservation_id":req.pk})
        req.refresh_from_db(); self.record.refresh_from_db()
        self.assertEqual(req.status,"delivered")
        self.assertEqual(self.record.status,"assigned")


class ArchivedUsersV30Tests(TestCase):
    def test_delete_action_archives_instead_of_deleting(self):
        User=get_user_model()
        gestor=User.objects.create_superuser(username="archive_gestor",password="gestor123",email="")
        target=User.objects.create_user(username="archive_target",password="user123")
        UserProfile.objects.create(user=gestor); UserProfile.objects.create(user=target)
        self.client.login(username="archive_gestor",password="gestor123")
        response=self.client.post(reverse("users_panel"),{"action":"delete","user_id":target.pk})
        self.assertRedirects(response,reverse("users_panel"))
        target.refresh_from_db(); target.inventory_profile.refresh_from_db()
        self.assertFalse(target.is_active)
        self.assertIsNotNone(target.inventory_profile.archived_at)

