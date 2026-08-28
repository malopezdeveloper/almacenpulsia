import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import discovery
import platform_tools
import app_config


class DiscoverySecurityTests(unittest.TestCase):
    def test_private_ip_allowed(self):
        self.assertTrue(discovery.is_allowed_server_ip("192.168.1.108"))
        self.assertTrue(discovery.is_allowed_server_ip("10.10.10.10"))

    def test_public_and_loopback_rejected(self):
        self.assertFalse(discovery.is_allowed_server_ip("8.8.8.8"))
        self.assertFalse(discovery.is_allowed_server_ip("127.0.0.1"))
        self.assertFalse(discovery.is_allowed_server_ip("224.0.0.1"))


class HostsTests(unittest.TestCase):
    def test_removes_only_pulsia_alias(self):
        line = "192.168.1.10 foo almacen bar # comentario"
        updated = platform_tools._remove_alias_from_hosts_line(line, "almacen")
        self.assertEqual(updated, "192.168.1.10\tfoo\tbar\t# comentario")

    def test_removes_entire_line_if_only_alias(self):
        self.assertIsNone(
            platform_tools._remove_alias_from_hosts_line("192.168.1.10 almacen", "almacen")
        )

    def test_rejects_arbitrary_hostname(self):
        with self.assertRaises(ValueError):
            platform_tools._validate_hosts_change("192.168.1.108", "evil-host")

    def test_rejects_public_ip(self):
        with self.assertRaises(ValueError):
            platform_tools._validate_hosts_change("8.8.8.8", "almacen")

    def test_dns_consistency_requires_hosts_and_resolver(self):
        with mock.patch.object(platform_tools, "current_host_ip", return_value="192.168.1.108"), \
             mock.patch.object(platform_tools, "resolved_host_ips", return_value=["192.168.1.108"]):
            self.assertTrue(platform_tools.dns_is_consistent("192.168.1.108"))

        with mock.patch.object(platform_tools, "current_host_ip", return_value="192.168.1.249"), \
             mock.patch.object(platform_tools, "resolved_host_ips", return_value=["192.168.1.249"]):
            self.assertFalse(platform_tools.dns_is_consistent("192.168.1.108"))

    def test_local_server_does_not_request_caddy_shutdown(self):
        with mock.patch.object(platform_tools, "dns_is_consistent", return_value=True), \
             mock.patch.object(platform_tools, "detect_local_caddy", return_value=[{"kind":"service","name":"PulsiaCaddy"}]), \
             mock.patch.object(platform_tools, "server_is_local_machine", return_value=True):
            needed, reasons = platform_tools.client_environment_needs_repair("192.168.1.108")
            self.assertFalse(needed)
            self.assertEqual(reasons, [])

    def test_remote_server_with_local_caddy_requests_repair(self):
        with mock.patch.object(platform_tools, "dns_is_consistent", return_value=True), \
             mock.patch.object(platform_tools, "detect_local_caddy", return_value=[{"kind":"service","name":"caddy","state":"running","start_mode":"enabled"}]), \
             mock.patch.object(platform_tools, "server_is_local_machine", return_value=False):
            needed, reasons = platform_tools.client_environment_needs_repair("192.168.1.108")
            self.assertTrue(needed)
            self.assertTrue(any("Caddy" in r for r in reasons))


class CertificateAndNetworkProtocolTests(unittest.TestCase):
    def test_bundled_ca_hash_is_file_sha256(self):
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            cert = Path(td) / "root.crt"
            cert.write_bytes(b"PULSIA TEST CA")
            with mock.patch.object(platform_tools, "bundled_ca_path", return_value=cert):
                self.assertEqual(
                    platform_tools.bundled_ca_sha256(),
                    hashlib.sha256(b"PULSIA TEST CA").hexdigest().upper(),
                )

    def test_windows_renew_is_not_used_when_dns_is_already_correct(self):
        with mock.patch.object(platform_tools.platform, "system", return_value="Windows"), \
             mock.patch.object(platform_tools, "dns_is_consistent", return_value=True), \
             mock.patch.object(platform_tools.subprocess, "run") as run:
            self.assertTrue(platform_tools.renew_windows_network_if_dns_still_wrong("192.168.1.108"))
            run.assert_not_called()


class DeploymentIdentityTests(unittest.TestCase):
    def test_deployment_server_imports_server_mac_and_port(self):
        data = {
            "SERVER_IP": "192.168.1.108",
            "SERVER_HOST": "almacen",
            "SERVER_PORT": "443",
            "SERVER_MAC": "AA:BB:CC:DD:EE:FF",
            "SERVER_SYSTEM_HOSTNAME": "workbench.local",
            "CA_SHA256": "ABCDEF",
        }
        with mock.patch.object(app_config, "load_deployment_ini", return_value=data):
            server = app_config._deployment_server()
        self.assertIsNotNone(server)
        self.assertEqual(server.ip, "192.168.1.108")
        self.assertEqual(server.mac, "AA:BB:CC:DD:EE:FF")
        self.assertEqual(server.port, 443)
        self.assertEqual(server.reverse_hostname, "workbench.local")


if __name__ == "__main__":
    unittest.main()
