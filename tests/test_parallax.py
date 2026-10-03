"""HTTP authorization, signing, and native plug-in compatibility with test-only keys."""
import csv
import io
import uuid
import base64
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("parallax_api", ROOT / "api/parallax.py")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class LicenseApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        (cls.root / "parallax").mkdir()
        cls.key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
        public = cls.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        (cls.root / "parallax/release.json").write_text(json.dumps({"public_key": public}))
        pem = cls.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        cls.password = "test-only-owner-password"
        cls.values = {"PARALLAX_ADMIN_PASSWORD_HASH": api.password_hash(cls.password),
                      "PARALLAX_SESSION_SECRET": "test-only-session-secret-" + "s" * 32,
                      "PARALLAX_SIGNING_KEY_BASE64": base64.b64encode(pem).decode(),
                      "PARALLAX_LOCAL": "1", "VERCEL": ""}
        cls.env = patch.dict(os.environ, cls.values)
        cls.env.start()
        cls.root_patch = patch.object(api, "ROOT", cls.root)
        cls.root_patch.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api.handler)
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.request_code = "PLX1-MAC-" + hashlib.blake2b(
            b"audio.sustx.parallax.beta\nrequest-v1\nMAC\ntest-computer-a", digest_size=32).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.root_patch.stop()
        cls.env.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.database = patch.dict(os.environ, {"PARALLAX_RECORDS_PATH": str(self.root / (str(uuid.uuid4()) + ".sqlite3"))})
        self.database.start()
        self.addCleanup(self.database.stop)

    def call(self, data=None, cookie=None, csrf=None, origin=None, raw=None, extra=None):
        headers = {"Origin": origin or self.origin, "Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        if csrf:
            headers["X-CSRF-Token"] = csrf
        headers.update(extra or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        body = raw if raw is not None else json.dumps(data) if data is not None else None
        connection.request("POST" if body is not None else "GET", "/api/parallax", body, headers)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def login(self):
        status, headers, body = self.call({"action": "login", "password": self.password})
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        return headers["Set-Cookie"].split(";")[0], json.loads(body)["csrf"]

    def issue(self, cookie, csrf, **overrides):
        data = {"action": "issue", "customer": "Tester A", "request": self.request_code}
        data.update(overrides)
        return self.call(data, cookie, csrf)

    def test_no_public_issuance(self):
        self.assertEqual(json.loads(self.call()[2])["authenticated"], False)
        self.assertEqual(self.issue(None, None)[0], 401)
        self.assertEqual(self.call({"action": "login", "password": "wrong"})[0], 401)

    def test_signed_machine_bound_file_and_native_verifier(self):
        cookie, csrf = self.login()
        status, headers, document = self.issue(cookie, csrf)
        self.assertEqual(status, 200)
        self.assertIn(".parallax-license", headers["Content-Disposition"])
        wrapper = json.loads(document)
        payload = base64.b64decode(wrapper["payload"], validate=True)
        self.key.public_key().verify(bytes.fromhex(wrapper["signature"]), payload)
        decoded = json.loads(payload)
        self.assertEqual(decoded["machine"], self.request_code)
        self.assertEqual(decoded["customer"], "Tester A")
        self.assertTrue(decoded["perpetual"])
        second = json.loads(base64.b64decode(json.loads(self.issue(cookie, csrf)[2])["payload"]))
        self.assertNotEqual(decoded["license_id"], second["license_id"])
        native = os.environ.get("PARALLAX_NATIVE_VERIFIER")
        if native:
            license_path = self.root / "web-issued.parallax-license"
            license_path.write_bytes(document)
            result = subprocess.run([native, str(license_path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_csrf_origin_and_logout(self):
        cookie, csrf = self.login()
        self.assertEqual(self.issue(cookie, None)[0], 403)
        self.assertEqual(self.issue(cookie, "wrong")[0], 403)
        self.assertEqual(self.call({"action": "issue"}, cookie, csrf, "https://other.example")[0], 403)
        self.assertEqual(self.call({"action": "logout"}, cookie, csrf)[0], 200)

    def test_bad_and_expired_cookies(self):
        cookie, csrf = self.login()
        self.assertEqual(self.issue(cookie + "x", csrf)[0], 401)
        with patch.object(api.time, "time", return_value=time.time() + api.SESSION_SECONDS + 5):
            self.assertEqual(self.issue(cookie, csrf)[0], 401)
        with patch.dict(os.environ, {"PARALLAX_SESSION_SECRET": "new-secret-" * 8}):
            self.assertEqual(self.issue(cookie, csrf)[0], 401)
        with patch.dict(os.environ, {"PARALLAX_ADMIN_PASSWORD_HASH": api.password_hash("replacement-password")}):
            self.assertEqual(self.issue(cookie, csrf)[0], 401)

    def test_bad_input_and_wrong_signing_identity(self):
        cookie, csrf = self.login()
        for change in ({"request": "PLX1-MAC-bad"}, {"customer": ""}, {"customer": "a" * 161},
                       {"customer": "A\nB"}, {"customer": []}, {"request": 9}):
            self.assertEqual(self.issue(cookie, csrf, **change)[0], 400)
        self.assertEqual(self.call(raw="{", cookie=cookie, csrf=csrf)[0], 400)
        self.assertEqual(self.call(raw="[]", cookie=cookie, csrf=csrf)[0], 400)
        self.assertEqual(self.call(raw="x" * (api.MAX_BODY + 1), cookie=cookie, csrf=csrf)[0], 413)
        self.assertEqual(self.call(raw="{}", extra={"Content-Type": "text/plain"})[0], 415)
        with patch.dict(os.environ, {"PARALLAX_SIGNING_KEY_BASE64": "invalid"}):
            self.assertEqual(self.issue(cookie, csrf)[0], 503)
        wrong = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        with patch.dict(os.environ, {"PARALLAX_SIGNING_KEY_BASE64": base64.b64encode(wrong).decode()}):
            self.assertEqual(self.issue(cookie, csrf)[0], 503)

    def test_private_persistent_history_download_and_export(self):
        cookie, csrf = self.login()
        _, _, document = self.issue(cookie, csrf, customer='=HYPERLINK("test")')
        payload = api.verify_document(document.decode())
        license_id = payload["license_id"]
        for action in ("history", "download", "export", "import"):
            self.assertEqual(self.call({"action": action}, None, None)[0], 401)
            self.assertEqual(self.call({"action": action}, cookie, None)[0], 403)
        records = json.loads(self.call({"action": "history"}, cookie, csrf)[2])["records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["license_id"], license_id)
        self.assertNotIn("document", records[0])
        self.assertEqual(api.LocalRecords().get(license_id)["document"].encode(), document)
        self.assertEqual(self.call({"action": "download", "license_id": license_id}, cookie, csrf)[2], document)
        exported = self.call({"action": "export"}, cookie, csrf)
        rows = list(csv.DictReader(io.StringIO(exported[2].decode("utf-8-sig"))))
        self.assertEqual(rows[0]["customer"], "'" + payload["customer"])
        self.assertEqual(rows[0]["license_id"], license_id)
        self.assertEqual(self.call({"action": "download", "license_id": str(uuid.uuid4())}, cookie, csrf)[0], 404)

    def test_import_validates_signature_and_deduplicates(self):
        cookie, csrf = self.login()
        document, _ = api.issue_license("Earlier customer", self.request_code)
        wrapper = json.loads(document)
        payload = api.verify_document(document.decode())
        for text in (document.decode(), json.dumps(wrapper), document.decode()):
            self.assertEqual(self.call({"action": "import", "document": text}, cookie, csrf)[0], 200)
        records = json.loads(self.call({"action": "history"}, cookie, csrf)[2])["records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source"], "imported")
        self.assertEqual(self.call({"action": "download", "license_id": payload["license_id"]}, cookie, csrf)[2], document)
        altered = dict(wrapper, signature="00" * 64)
        self.assertEqual(self.call({"action": "import", "document": json.dumps(altered)}, cookie, csrf)[0], 400)
        payload["customer"] = "Different customer"
        raw = json.dumps(payload).encode()
        conflicting = json.dumps({"payload": base64.b64encode(raw).decode(), "signature": self.key.sign(raw).hex()})
        self.assertEqual(self.call({"action": "import", "document": conflicting}, cookie, csrf)[0], 409)
        self.assertEqual(len(api.LocalRecords().all()), 1)

    def test_storage_failure_prevents_unrecorded_issuance(self):
        cookie, csrf = self.login()
        with patch.object(api, "record_store", side_effect=api.StorageError("Unavailable")):
            status, headers, body = self.issue(cookie, csrf)
            self.assertEqual(status, 503)
            self.assertNotIn("Content-Disposition", headers)
            self.assertEqual(json.loads(body)["error"], "Unavailable")
        self.assertEqual(api.LocalRecords().all(), [])
        with patch.dict(os.environ, {"VERCEL": "1", "BLOB_READ_WRITE_TOKEN": ""}):
            with self.assertRaises(api.StorageError):
                api.record_store()

    def test_missing_configuration_and_production_cookie(self):
        with patch.dict(os.environ, {"PARALLAX_SESSION_SECRET": ""}):
            self.assertEqual(self.call()[0], 503)
            self.assertEqual(self.issue(None, None)[0], 503)
        with patch.dict(os.environ, {"VERCEL": "1"}):
            self.assertIn("Secure", api.session_cookie("test"))
            self.assertTrue(api.session_cookie("test").startswith("__Host-parallax_admin="))


if __name__ == "__main__":
    unittest.main()
