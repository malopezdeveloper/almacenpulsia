from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
import threading


def _dependency_error(message: str) -> None:
    text = (
        "PULSIA Inventario Cliente no puede arrancar porque faltan dependencias.\n\n"
        + message
        + "\n\nWindows: ejecuta ARRANCAR_WINDOWS.bat\n"
        + "Linux: ejecuta ./arrancar_linux.sh"
    )
    print(text, file=sys.stderr)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, "PULSIA Inventario", 0x10)
        except Exception:
            pass


try:
    from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Signal, Slot
    from PySide6.QtGui import QAction, QFont
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
        QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
        QStackedWidget, QStatusBar, QToolBar, QVBoxLayout, QWidget
    )
except ModuleNotFoundError as exc:
    _dependency_error(f"Módulo no disponible: {exc.name}")
    raise SystemExit(3)
except ImportError as exc:
    _dependency_error(str(exc))
    raise SystemExit(3)

from app_config import AppConfig, SERVICE_HOSTNAME, ServerInfo, UserPreferences, bundled_ca_path, load_config, load_deployment_ini, save_config
from browser import create_web_view, purge_persistent_profile
from credentials import delete_password, keyring_available, load_password, save_password
from discovery import ProbeResult, discover_servers, is_allowed_server_ip, probe_server
from platform_tools import (
    bundled_ca_exists,
    bundled_ca_sha256,
    ca_is_installed,
    client_environment_needs_repair,
    current_host_ip,
    install_bundled_ca,
    repair_client_environment,
    request_ca_install,
    request_client_repair,
    update_hosts_file,
    verify_https_system_trust,
)

APP_TITLE = "PULSIA Inventario"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--configure-hosts", nargs=2, metavar=("IP", "HOSTNAME"))
    parser.add_argument("--repair-client", nargs=2, metavar=("IP", "HOSTNAME"))
    parser.add_argument("--install-ca", action="store_true")
    parser.add_argument("--self-test-runtime", action="store_true")
    return parser.parse_args()


class AsyncBridge(QObject):
    known_probe_done = Signal(object)
    manual_probe_done = Signal(object)


class ScanWorker(QObject):
    progress = Signal(int, int, str)
    found = Signal(object)
    finished = Signal()
    error = Signal(str)

    def __init__(self, preferred):
        super().__init__()
        self.preferred = preferred

    @Slot()
    def run(self):
        try:
            servers = discover_servers(
                preferred=self.preferred,
                progress_cb=lambda n, total, ip: self.progress.emit(n, total, ip),
            )
            if servers:
                self.found.emit(servers[0])
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config: AppConfig = load_config()
        self.web_view = None
        self.scan_thread = None
        self.scan_worker = None
        self.server_found_this_scan = False

        if not self.config.user.keep_session:
            purge_persistent_profile()

        self.bridge = AsyncBridge(self)
        self.bridge.known_probe_done.connect(self._known_probe_done)
        self.bridge.manual_probe_done.connect(self._manual_probe_done)

        self.setWindowTitle(APP_TITLE)
        self.resize(1200, 800)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.setStatusBar(QStatusBar())

        self.setup_page = self._build_setup_page()
        self.stack.addWidget(self.setup_page)

        self.toolbar = QToolBar("PULSIA")
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)
        self.toolbar.hide()

        self._restore_preferences()

        if self.config.server:
            QTimer.singleShot(300, self.try_known_server)

    def _build_setup_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(48, 40, 48, 40)
        root.setSpacing(20)

        title = QLabel("PULSIA Inventario")
        font = QFont()
        font.setPointSize(24)
        font.setBold(True)
        title.setFont(font)
        root.addWidget(title)

        subtitle = QLabel("Localiza el servidor de inventario en la red o introduce su dirección IP.")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        server_box = QGroupBox("Servidor")
        server_layout = QVBoxLayout(server_box)

        row = QHBoxLayout()
        self.ip_edit = QLineEdit()
        self.ip_edit.setPlaceholderText("Ej. 192.168.1.108")
        self.connect_btn = QPushButton("Conectar por IP")
        self.connect_btn.clicked.connect(self.connect_manual)
        row.addWidget(self.ip_edit, 1)
        row.addWidget(self.connect_btn)
        server_layout.addLayout(row)

        self.scan_btn = QPushButton("Buscar servidor automáticamente en la red")
        self.scan_btn.clicked.connect(self.scan_network)
        server_layout.addWidget(self.scan_btn)

        self.service_connect_btn = QPushButton("Conectar con el servicio")
        self.service_connect_btn.setEnabled(False)
        self.service_connect_btn.clicked.connect(self.open_browser)
        server_layout.addWidget(self.service_connect_btn)

        self.progress = QProgressBar()
        self.progress.hide()
        server_layout.addWidget(self.progress)

        self.scan_label = QLabel("")
        self.scan_label.setWordWrap(True)
        server_layout.addWidget(self.scan_label)
        root.addWidget(server_box)

        access_box = QGroupBox("Opciones de acceso")
        form = QFormLayout(access_box)

        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.remember_user = QCheckBox("Recordar usuario")
        self.remember_password = QCheckBox("Recordar contraseña de forma segura")
        self.keep_session = QCheckBox("Mantener sesión iniciada al cerrar la aplicación")
        self.keep_session.setChecked(False)

        form.addRow("Usuario:", self.username_edit)
        form.addRow("Contraseña:", self.password_edit)
        form.addRow("", self.remember_user)
        form.addRow("", self.remember_password)
        form.addRow("", self.keep_session)

        if not keyring_available():
            warn = QLabel(
                "El almacén seguro de contraseñas no está disponible. "
                "La contraseña no se guardará hasta disponer de un keyring compatible."
            )
            warn.setWordWrap(True)
            form.addRow("", warn)

        root.addWidget(access_box)

        self.last_server_label = QLabel("")
        self.last_server_label.setWordWrap(True)
        root.addWidget(self.last_server_label)
        root.addStretch(1)
        return page

    def _restore_preferences(self):
        user = self.config.user
        self.remember_user.setChecked(user.remember_username)
        self.remember_password.setChecked(user.remember_password)
        self.keep_session.setChecked(user.keep_session)

        if user.remember_username:
            self.username_edit.setText(user.username)
        if user.remember_password and user.username:
            self.password_edit.setText(load_password(user.username))

        if self.config.server:
            s = self.config.server
            details = [f"Último servidor: {s.ip}"]
            if s.mac:
                details.append(f"MAC: {s.mac}")
            if s.reverse_hostname:
                details.append(f"Hostname: {s.reverse_hostname}")
            self.last_server_label.setText(" · ".join(details))
            self.ip_edit.setText(s.ip)

    def save_preferences(self):
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        old_username = self.config.user.username

        self.config.user = UserPreferences(
            username=username if self.remember_user.isChecked() else "",
            remember_username=self.remember_user.isChecked(),
            remember_password=self.remember_password.isChecked(),
            keep_session=self.keep_session.isChecked(),
        )

        if old_username and old_username != username:
            delete_password(old_username)

        if self.remember_password.isChecked() and username and password:
            if not save_password(username, password):
                self.remember_password.setChecked(False)
                self.config.user.remember_password = False
        elif username:
            delete_password(username)

        save_config(self.config)

    def set_busy(self, busy: bool, text: str = ""):
        self.connect_btn.setEnabled(not busy)
        self.scan_btn.setEnabled(not busy)
        self.ip_edit.setEnabled(not busy)
        if busy:
            self.service_connect_btn.setEnabled(False)
            self.progress.show()
            if text:
                self.scan_label.setText(text)
        else:
            self.progress.hide()

    @Slot()
    def try_known_server(self):
        if not self.config.server:
            return
        self.set_busy(True, f"Comprobando servidor conocido {self.config.server.ip}…")

        def job():
            result = probe_server(self.config.server.ip, timeout=2.0)
            self.bridge.known_probe_done.emit(result)

        threading.Thread(target=job, daemon=True).start()

    @Slot(object)
    def _known_probe_done(self, result: ProbeResult):
        self.set_busy(False)
        if result.server:
            self.accept_server(result.server, automatic=True)
        else:
            self.scan_label.setText(
                "El servidor guardado no responde en su última IP. Puedes buscarlo en la red."
            )

    @Slot()
    def connect_manual(self):
        ip = self.ip_edit.text().strip()
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            QMessageBox.warning(self, APP_TITLE, "Introduce una dirección IPv4 válida.")
            return
        if not is_allowed_server_ip(ip):
            QMessageBox.warning(self, APP_TITLE, "La IP debe pertenecer a la red local.")
            return

        self.set_busy(True, f"Comprobando PULSIA Inventario en {ip}…")

        def job():
            result = probe_server(ip, timeout=3.0)
            self.bridge.manual_probe_done.emit(result)

        threading.Thread(target=job, daemon=True).start()

    @Slot(object)
    def _manual_probe_done(self, result: ProbeResult):
        self.set_busy(False)
        if result.server:
            self.accept_server(result.server, automatic=False)
        else:
            QMessageBox.warning(
                self, APP_TITLE,
                "No se ha detectado PULSIA Inventario en esa IP.\n\n" + result.error
            )

    @Slot()
    def scan_network(self):
        if self.scan_thread and self.scan_thread.isRunning():
            return
        self.server_found_this_scan = False
        self.set_busy(True, "Escaneando la red local…")
        self.progress.setValue(0)

        self.scan_thread = QThread(self)
        self.scan_worker = ScanWorker(self.config.server)
        self.scan_worker.moveToThread(self.scan_thread)
        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_worker.progress.connect(self.on_scan_progress)
        self.scan_worker.found.connect(self.on_server_found)
        self.scan_worker.error.connect(lambda msg: QMessageBox.warning(self, APP_TITLE, msg))
        self.scan_worker.finished.connect(self.on_scan_finished)
        self.scan_worker.finished.connect(self.scan_thread.quit)
        self.scan_thread.finished.connect(self.scan_thread.deleteLater)
        self.scan_thread.start()

    @Slot(int, int, str)
    def on_scan_progress(self, checked, total, ip):
        pct = int((checked / max(total, 1)) * 100)
        self.progress.setValue(min(100, pct))
        self.scan_label.setText(f"Buscando… {checked}/{total} · {ip}")

    @Slot(object)
    def on_server_found(self, server):
        self.server_found_this_scan = True
        self.accept_server(server, automatic=False)

    @Slot()
    def on_scan_finished(self):
        self.set_busy(False)
        if self.stack.currentWidget() == self.setup_page and not self.server_found_this_scan:
            self.scan_label.setText("Búsqueda finalizada sin encontrar un servidor.")

    def accept_server(self, server: ServerInfo, automatic: bool = False):
        previous = self.config.server
        if previous and not server.mac and previous.mac:
            server.mac = previous.mac

        self.config.server = server
        self.save_preferences()
        self.service_connect_btn.setEnabled(False)

        self.scan_label.setText(
            f"Servidor encontrado: {server.ip}" + (f" · MAC {server.mac}" if server.mac else "")
        )

        # 1) Sanear resolución/Caddy del puesto antes de validar el HTTPS real.
        needs_repair, reasons = client_environment_needs_repair(server.ip, SERVICE_HOSTNAME)
        if needs_repair:
            self.scan_label.setText(
                "Servidor encontrado. Reparando DNS/hosts y conflictos Caddy del cliente…"
            )
            if not request_client_repair(server.ip, SERVICE_HOSTNAME):
                QMessageBox.warning(
                    self, APP_TITLE,
                    "El servidor ha sido encontrado, pero no se pudo completar el saneamiento "
                    "del equipo cliente.\n\n"
                    + "\n".join(f"• {reason}" for reason in reasons)
                    + "\n\nSe requieren permisos de administrador/root para corregir la resolución "
                    "y detener Caddy local si existe."
                )
                return

        # 2) La CA debe viajar con esta copia USB, preparada por el instalador del servidor.
        if not bundled_ca_exists():
            QMessageBox.critical(
                self, APP_TITLE,
                "Falta el certificado de confianza generado por el servidor.\n\n"
                f"Esperado en:\n{bundled_ca_path()}\n\n"
                "Utiliza la carpeta cliente generada por la instalación de PULSIA Inventario."
            )
            self.scan_label.setText("✗ Falta la CA raíz PULSIA en la carpeta del cliente.")
            return

        deployment = load_deployment_ini()
        expected_ca = deployment.get("CA_SHA256", "").strip().upper()
        actual_ca = bundled_ca_sha256().upper()
        if expected_ca and actual_ca != expected_ca:
            QMessageBox.critical(
                self, APP_TITLE,
                "El certificado de la carpeta cliente no coincide con el generado para este servidor.\n\n"
                "Vuelve a extraer PULSIA_Inventario_Cliente_USB.zip desde la instalación del servidor."
            )
            self.scan_label.setText("✗ La CA del cliente no corresponde a esta instalación PULSIA.")
            return

        # 3) Instalar la CA en el trust store del puesto. En Windows solicita UAC solo si hace falta.
        if not request_ca_install():
            QMessageBox.warning(
                self, APP_TITLE,
                "No se pudo instalar la CA raíz PULSIA en el almacén de confianza del equipo.\n\n"
                "Acepta la elevación de administrador y vuelve a comprobar el servidor."
            )
            self.scan_label.setText("✗ Certificado PULSIA no instalado en el equipo cliente.")
            return

        # 4) Comprobación final: HTTPS debe validar normalmente, sin ignorar errores TLS.
        ok_tls, tls_detail = verify_https_system_trust(server.ip, SERVICE_HOSTNAME)
        if not ok_tls:
            QMessageBox.warning(
                self, APP_TITLE,
                "La red está preparada, pero HTTPS todavía no valida correctamente.\n\n"
                f"{tls_detail}\n\n"
                "Cierra procesos/navegadores que mantengan configuración antigua y vuelve a comprobar."
            )
            self.scan_label.setText("✗ HTTPS no valida con la CA PULSIA instalada.")
            return

        ca_hash = bundled_ca_sha256()
        self.scan_label.setText(
            f"✓ Servidor: {server.ip}\n"
            f"✓ {SERVICE_HOSTNAME} resuelve correctamente\n"
            f"✓ Caché DNS saneada\n"
            f"✓ CA PULSIA disponible e instalada\n"
            f"✓ HTTPS/443 validado"
            + (f"\nCA SHA-256: {ca_hash[:16]}…" if ca_hash else "")
        )
        self.statusBar().showMessage("Comprobaciones correctas. Puedes conectar con el servicio.")
        self.service_connect_btn.setEnabled(True)

    def open_browser(self):
        self.save_preferences()
        if not self.config.server:
            QMessageBox.warning(self, APP_TITLE, "No hay un servidor configurado.")
            return

        if self.web_view is not None:
            try:
                self.stack.removeWidget(self.web_view)
                self.web_view.deleteLater()
            except Exception:
                pass

        self.web_view = create_web_view(self.keep_session.isChecked(), self)
        self.web_view.loadStarted.connect(self.on_web_load_started)
        self.web_view.loadProgress.connect(self.on_web_load_progress)
        self.web_view.loadFinished.connect(self.on_web_loaded)
        self.stack.addWidget(self.web_view)
        self.stack.setCurrentWidget(self.web_view)
        self._build_toolbar()
        self.toolbar.show()

        self.statusBar().showMessage(
            f"Servidor: {self.config.server.ip} · https://{SERVICE_HOSTNAME}"
        )
        self.web_view.setUrl(QUrl(f"https://{SERVICE_HOSTNAME}/"))
        self.showMaximized()

    def _build_toolbar(self):
        self.toolbar.clear()

        home = QAction("Inicio", self)
        home.triggered.connect(lambda: self.web_view and self.web_view.setUrl(QUrl(f"https://{SERVICE_HOSTNAME}/")))
        self.toolbar.addAction(home)

        reload_action = QAction("Recargar", self)
        reload_action.triggered.connect(lambda: self.web_view and self.web_view.reload())
        self.toolbar.addAction(reload_action)

        server = QAction("Servidor", self)
        server.triggered.connect(self.back_to_setup)
        self.toolbar.addAction(server)

        logout = QAction("Cerrar sesión", self)
        logout.triggered.connect(
            lambda: self.web_view and self.web_view.setUrl(QUrl(f"https://{SERVICE_HOSTNAME}/cuenta/logout/"))
        )
        self.toolbar.addAction(logout)

        fullscreen = QAction("Pantalla completa", self)
        fullscreen.triggered.connect(self.toggle_fullscreen)
        self.toolbar.addAction(fullscreen)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    def back_to_setup(self):
        self.stack.setCurrentWidget(self.setup_page)
        self.toolbar.hide()

    @Slot()
    def on_web_load_started(self):
        if self.config.server:
            self.statusBar().showMessage(
                f"Conectando con {self.config.server.ip} · https://{SERVICE_HOSTNAME}…"
            )

    @Slot(int)
    def on_web_load_progress(self, progress):
        self.statusBar().showMessage(f"Cargando PULSIA Inventario… {progress}%")

    @Slot(bool)
    def on_web_loaded(self, ok):
        if not self.web_view:
            return
        if not ok:
            ip = self.config.server.ip if self.config.server else "desconocida"
            self.statusBar().showMessage("No se pudo mostrar la interfaz web.")
            QMessageBox.warning(
                self, APP_TITLE,
                "El servidor fue localizado, pero Qt WebEngine no pudo cargar la web.\n\n"
                f"Servidor: {ip}\nURL: https://{SERVICE_HOSTNAME}\n\n"
                "Comprueba que el servicio siga disponible y pulsa Recargar."
            )
            return
        self.statusBar().showMessage(
            f"Conectado · {self.config.server.ip if self.config.server else ''} · https://{SERVICE_HOSTNAME}"
        )
        url = self.web_view.url()
        if url.scheme().lower() != "https" or url.host().lower() != SERVICE_HOSTNAME.lower():
            return
        if not url.path().startswith("/cuenta/login"):
            return

        username = self.username_edit.text().strip()
        password = self.password_edit.text() if self.remember_password.isChecked() else ""
        if not username:
            return

        username_js = json.dumps(username)
        password_js = json.dumps(password)
        js = f"""
        (() => {{
          const u = document.querySelector('input[name="username"], input[name="user"], input[type="email"]');
          const p = document.querySelector('input[name="password"], input[type="password"]');
          if (u && !u.value) {{
            u.value = {username_js};
            u.dispatchEvent(new Event('input', {{bubbles:true}}));
            u.dispatchEvent(new Event('change', {{bubbles:true}}));
          }}
          const savedPassword = {password_js};
          if (p && !p.value && savedPassword) {{
            p.value = savedPassword;
            p.dispatchEvent(new Event('input', {{bubbles:true}}));
            p.dispatchEvent(new Event('change', {{bubbles:true}}));
          }}
        }})();
        """
        self.web_view.page().runJavaScript(js)


    def closeEvent(self, event):
        self.save_preferences()
        if not self.keep_session.isChecked() and self.web_view:
            try:
                self.web_view.page().profile().cookieStore().deleteAllCookies()
                self.web_view.page().profile().clearHttpCache()
            except Exception:
                pass
        super().closeEvent(event)


def configure_hosts_mode(ip: str, hostname: str) -> int:
    try:
        if hostname.lower() != SERVICE_HOSTNAME.lower() or not is_allowed_server_ip(ip):
            raise ValueError("Parámetros de configuración no permitidos.")
        update_hosts_file(ip, hostname)
        return 0
    except Exception as exc:
        print(f"ERROR configurando hosts: {exc}", file=sys.stderr)
        return 2


def repair_client_mode(ip: str, hostname: str) -> int:
    try:
        if hostname.lower() != SERVICE_HOSTNAME.lower() or not is_allowed_server_ip(ip):
            raise ValueError("Parámetros de reparación no permitidos.")
        actions = repair_client_environment(ip, hostname)
        for action in actions:
            print(action)
        return 0
    except Exception as exc:
        print(f"ERROR reparando cliente: {exc}", file=sys.stderr)
        return 2


def install_ca_mode() -> int:
    try:
        actions = install_bundled_ca()
        for action in actions:
            print(action)
        return 0
    except Exception as exc:
        print(f"ERROR instalando CA: {exc}", file=sys.stderr)
        return 2



def self_test_runtime() -> int:
    """Validate the packaged Qt runtime without contacting the PULSIA server."""
    try:
        from PySide6.QtNetwork import QSslSocket
        from PySide6.QtWebEngineCore import QWebEngineProfile

        app = QApplication.instance() or QApplication(sys.argv[:1])
        if not QSslSocket.supportsSsl():
            print("SELFTEST ERROR: Qt SSL no está disponible.", file=sys.stderr)
            return 10

        ssl_version = QSslSocket.sslLibraryVersionString() or ""
        build_version = QSslSocket.sslLibraryBuildVersionString() or ""
        print(f"SELFTEST Qt SSL runtime: {ssl_version}")
        print(f"SELFTEST Qt SSL build: {build_version}")

        # Creating a WebEngine profile verifies that the Chromium/QtWebEngine
        # runtime can be initialized by the packaged application.
        profile = QWebEngineProfile()
        profile.deleteLater()
        app.processEvents()
        print("SELFTEST QtWebEngine: OK")
        return 0
    except Exception as exc:
        print(f"SELFTEST ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 11


def main() -> int:
    args = parse_args()
    if args.configure_hosts:
        return configure_hosts_mode(*args.configure_hosts)
    if args.repair_client:
        return repair_client_mode(*args.repair_client)
    if args.install_ca:
        return install_ca_mode()
    if args.self_test_runtime:
        return self_test_runtime()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setOrganizationName("PULSIA")

    window = MainWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
