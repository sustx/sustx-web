"""Private Parallax administration and invitation-scoped customer unlocks."""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import csv
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler
import json
import io
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "audio.sustx.parallax.beta"  # Existing plug-in protocol ID; never displayed.
REQUEST = re.compile(r"PLX1-(?:MAC|WIN)-[0-9a-f]{64}\Z")
SESSION_SECONDS = 8 * 60 * 60
MAX_BODY = 24576
MAX_LICENSE_BYTES = 16384
RECORD_PREFIX = "parallax/licenses/"
COLLECTIONS = {"licenses": RECORD_PREFIX, "invitations": "parallax/invitations/",
               "revocations": "parallax/invitation-revocations/"}
INVITE_TOKEN = re.compile(r"PLXI-([0-9a-f]{32})-([A-Za-z0-9_-]{43})\Z")


class InvitationError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class ConfigurationError(Exception):
    pass


class StorageError(Exception):
    pass


class RecordConflict(Exception):
    pass


def canonical_id(value):
    if not isinstance(value, str):
        raise ValueError("Choose a license from the history.")
    return str(uuid.UUID(value))


def verify_document(document):
    """Validate archived/imported files against the same identity as the plugin."""
    if not isinstance(document, str) or len(document.encode()) > MAX_LICENSE_BYTES:
        raise ValueError("Choose a Parallax license file smaller than 16 KB.")
    try:
        wrapper = json.loads(document)
        payload = base64.b64decode(wrapper["payload"], validate=True)
        signature = bytes.fromhex(wrapper["signature"])
        public = bytes.fromhex(json.loads((ROOT / "parallax/release.json").read_text())["public_key"])
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(public).verify(signature, payload)
        data = json.loads(payload)
        if (data["product"] != PRODUCT or type(data["schema"]) is not int or data["schema"] != 1
                or data["perpetual"] is not True or not REQUEST.fullmatch(data["machine"])
                or not isinstance(data["customer"], str) or not data["customer"].strip()
                or len(data["customer"].encode()) > 160 or any(ord(c) < 32 for c in data["customer"])
                or canonical_id(data["license_id"]) != data["license_id"]):
            raise ValueError()
        issued = datetime.fromisoformat(data["issued_at"])
        if issued.tzinfo is None:
            raise ValueError()
    except Exception:
        # Do not echo untrusted file contents or signing errors into responses.
        raise ValueError("This file is not a valid license for the current Parallax release.") from None
    return data


def same_document(first, second):
    first, second = json.loads(first), json.loads(second)
    return (base64.b64decode(first["payload"], validate=True) == base64.b64decode(second["payload"], validate=True)
            and bytes.fromhex(first["signature"]) == bytes.fromhex(second["signature"]))


def record_summary(record):
    return {key: record.get(key, "") for key in ("license_id", "customer", "email", "machine", "platform",
                                                "issued_at", "recorded_at", "source", "invite_id")}


class LocalRecords:
    """Durable local preview/test storage; never used on Vercel."""
    def __init__(self):
        self.path = Path(os.environ.get("PARALLAX_RECORDS_PATH", ROOT / ".private/parallax-records.sqlite3"))

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        self.path.chmod(0o600)
        connection.execute("CREATE TABLE IF NOT EXISTS licenses (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS private_entries (kind TEXT, id TEXT, record TEXT NOT NULL, PRIMARY KEY (kind, id))")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, license_id):
        try:
            with self.connection() as connection:
                row = connection.execute("SELECT record FROM licenses WHERE id = ?", (license_id,)).fetchone()
            return json.loads(row[0]) if row else None
        except (OSError, sqlite3.Error, ValueError):
            raise StorageError("Customer records are unavailable. Please try again.") from None

    def create_named(self, kind, key, value):
        if kind not in COLLECTIONS:
            raise ValueError("Unknown collection.")
        key = canonical_id(key)
        try:
            with self.connection() as connection:
                if kind == "licenses":
                    connection.execute("INSERT OR IGNORE INTO licenses VALUES (?, ?)", (key, json.dumps(value)))
                    row = connection.execute("SELECT record FROM licenses WHERE id = ?", (key,)).fetchone()
                else:
                    connection.execute("INSERT OR IGNORE INTO private_entries VALUES (?, ?, ?)", (kind, key, json.dumps(value)))
                    row = connection.execute("SELECT record FROM private_entries WHERE kind = ? AND id = ?", (kind, key)).fetchone()
            return json.loads(row[0])
        except (OSError, sqlite3.Error):
            raise StorageError("The record could not be saved. Please try again.") from None

    def get_named(self, kind, key):
        if kind == "licenses":
            return self.get(key)
        if kind not in COLLECTIONS:
            raise ValueError("Unknown collection.")
        try:
            with self.connection() as connection:
                row = connection.execute("SELECT record FROM private_entries WHERE kind = ? AND id = ?", (kind, key)).fetchone()
            return json.loads(row[0]) if row else None
        except (OSError, sqlite3.Error):
            raise StorageError("Records are unavailable. Please try again.") from None

    def list_named(self, kind):
        if kind == "licenses":
            return self.all()
        if kind not in COLLECTIONS:
            raise ValueError("Unknown collection.")
        try:
            with self.connection() as connection:
                rows = connection.execute("SELECT record FROM private_entries WHERE kind = ?", (kind,)).fetchall()
            return [json.loads(row[0]) for row in rows]
        except (OSError, sqlite3.Error):
            raise StorageError("Records are unavailable. Please try again.") from None

    def save(self, record):
        saved = self.create_named("licenses", record["license_id"], record)
        if not same_document(saved["document"], record["document"]):
            raise RecordConflict("That license ID already belongs to a different file.")
        return saved

    def all(self):
        try:
            with self.connection() as connection:
                rows = connection.execute("SELECT record FROM licenses").fetchall()
            return [json.loads(row[0]) for row in rows]
        except (OSError, sqlite3.Error, ValueError):
            raise StorageError("Customer records are unavailable. Please try again.") from None


class PrivateBlobRecords:
    def __init__(self):
        if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
            raise StorageError("Customer record storage has not been configured.")

    def get_named(self, kind, key):
        from vercel.blob import BlobClient
        from vercel.blob.errors import BlobNotFoundError
        path = COLLECTIONS[kind] + canonical_id(key) + ".json"
        try:
            with BlobClient() as client:
                result = client.get(path, access="private", use_cache=False)
            return json.loads(result.content)
        except BlobNotFoundError:
            return None
        except Exception:
            raise StorageError("Records are unavailable. Please try again.") from None

    def create_named(self, kind, key, value):
        from vercel.blob import BlobClient
        existing = self.get_named(kind, key)
        if existing is not None:
            return existing
        try:
            with BlobClient() as client:
                result = client.put(COLLECTIONS[kind] + canonical_id(key) + ".json",
                                    json.dumps(value).encode(), access="private", content_type="application/json",
                                    add_random_suffix=False, overwrite=False)
                if ".private.blob.vercel-storage.com/" not in result.url:
                    raise StorageError("Record storage must be private.")
        except Exception:
            # Conditional creation elects one winner; always use its original data.
            saved = self.get_named(kind, key)
            if saved is not None:
                return saved
            raise StorageError("The record could not be saved. Please try again.") from None
        return value

    def get(self, license_id):
        return self.get_named("licenses", license_id)

    def save(self, record):
        saved = self.create_named("licenses", record["license_id"], record)
        if not same_document(saved["document"], record["document"]):
            raise RecordConflict("That license ID already belongs to a different file.")
        return saved

    def list_named(self, kind):
        from vercel.blob import BlobClient
        try:
            with BlobClient() as client:
                items = list(client.iter_objects(prefix=COLLECTIONS[kind], batch_size=1000))
            ids = [canonical_id(Path(item.pathname).stem) for item in items if item.pathname.endswith(".json")]
            with ThreadPoolExecutor(max_workers=8) as pool:
                records = list(pool.map(lambda key: self.get_named(kind, key), ids))
            return [record for record in records if record is not None]
        except Exception:
            raise StorageError("Records are unavailable. Please try again.") from None

    def all(self):
        return self.list_named("licenses")


def record_store():
    return LocalRecords() if local_mode() else PrivateBlobRecords()


def make_record(document, source, email="", invite_id=""):
    text = document.decode() if isinstance(document, bytes) else document
    data = verify_document(text)
    record = {**{key: data[key] for key in ("license_id", "customer", "machine", "issued_at")},
              "platform": "macOS" if data["machine"].startswith("PLX1-MAC-") else "Windows",
              "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "source": source, "document": text}
    if email:
        record["email"] = email
    if invite_id:
        record["invite_id"] = invite_id
    return record


def save_record(document, source):
    return record_store().save(make_record(document, source))


def export_csv(records):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    keys = ("customer", "email", "license_id", "machine", "platform", "issued_at", "recorded_at", "source", "invite_id")
    writer.writerow(keys)
    for record in records:
        values = []
        for key in keys:
            value = str(record.get(key, ""))
            # Spreadsheet formula injection must not be possible through names.
            values.append("'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value)
        writer.writerow(values)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600000)
    return f"pbkdf2_sha256$600000${salt}${digest.hex()}"


def auth_settings():
    encoded = os.environ.get("PARALLAX_ADMIN_PASSWORD_HASH", "")
    secret = os.environ.get("PARALLAX_SESSION_SECRET", "")
    try:
        algorithm, iterations, salt, digest = encoded.split("$")
        if (algorithm != "pbkdf2_sha256" or int(iterations) != 600000
                or len(bytes.fromhex(salt)) != 16 or len(bytes.fromhex(digest)) != 32
                or len(secret) < 32):
            raise ValueError()
    except (ValueError, TypeError):
        raise ConfigurationError("Owner access has not been configured.") from None
    return encoded, secret.encode()


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def session_token(secret, password_digest):
    claims = {"expires": int(time.time()) + SESSION_SECONDS,
              "csrf": secrets.token_urlsafe(24),
              "identity": hashlib.sha256(password_digest.encode()).hexdigest()}
    payload = b64url(json.dumps(claims, separators=(",", ":")).encode())
    signature = b64url(hmac.digest(secret, payload.encode(), "sha256"))
    return f"{payload}.{signature}", claims


def read_session(cookie_header):
    encoded, secret = auth_settings()
    try:
        cookie = SimpleCookie()
        cookie.load(cookie_header or "")
        token = cookie[cookie_name()].value
        if len(token) > 2048:
            return None
        payload, signature = token.split(".")
        if not hmac.compare_digest(signature, b64url(hmac.digest(secret, payload.encode(), "sha256"))):
            return None
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if (type(claims.get("expires")) is not int or claims["expires"] <= time.time()
                or claims["expires"] > time.time() + SESSION_SECONDS
                or not isinstance(claims.get("csrf"), str)
                or not hmac.compare_digest(claims.get("identity", ""), hashlib.sha256(encoded.encode()).hexdigest())):
            return None
        return claims
    except (KeyError, ValueError, TypeError, CookieError):
        return None


def local_mode():
    return os.environ.get("PARALLAX_LOCAL") == "1" and not os.environ.get("VERCEL")


def cookie_name():
    return "parallax_admin" if local_mode() else "__Host-parallax_admin"


def session_cookie(token, max_age=SESSION_SECONDS):
    secure = "" if local_mode() else "; Secure"
    return f"{cookie_name()}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}"


def issue_license(customer, request, license_id=None, issued_at=None):
    if not isinstance(customer, str) or not isinstance(request, str):
        raise ValueError("Enter a customer name and the complete request code.")
    customer, request = customer.strip(), request.strip()
    if not customer or len(customer.encode("utf-8")) > 160 or any(ord(c) < 32 for c in customer):
        raise ValueError("Use a name up to 160 UTF-8 bytes, without line breaks.")
    if not REQUEST.fullmatch(request):
        raise ValueError("Copy the complete PLX1-MAC-… or PLX1-WIN-… code from Parallax.")
    try:
        pem = base64.b64decode(os.environ["PARALLAX_SIGNING_KEY_BASE64"], validate=True)
        key = serialization.load_pem_private_key(pem, password=None)
        expected = json.loads((ROOT / "parallax/release.json").read_text())["public_key"]
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError()
        actual = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        if not hmac.compare_digest(actual, expected):
            raise ValueError()
    except (KeyError, ValueError, OSError, TypeError):
        raise ConfigurationError("License signing is not configured for this release.") from None
    license_id = license_id or str(uuid.uuid4())
    payload = json.dumps({"schema": 1, "product": PRODUCT, "license_id": license_id,
                          "customer": customer, "machine": request, "perpetual": True,
                          "issued_at": issued_at or datetime.now(timezone.utc).isoformat(timespec="seconds")},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    document = json.dumps({"payload": base64.b64encode(payload).decode(),
                           "signature": key.sign(payload).hex()}, indent=2).encode() + b"\n"
    return document, f"Parallax-{license_id}.parallax-license"


def email_address(value, optional=False):
    if not isinstance(value, str):
        raise ValueError("Enter an email address.")
    value = value.strip().lower()
    if optional and not value:
        return ""
    if len(value.encode()) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value) or any(ord(c) < 32 for c in value):
        raise ValueError("Enter a valid email address.")
    return value


def create_invitation(data):
    email = email_address(data.get("email", ""), optional=True)
    days = data.get("days", 7)
    if type(days) is not int or not 1 <= days <= 90:
        raise ValueError("Choose an expiry between 1 and 90 days.")
    now = datetime.now(timezone.utc)
    invite_id = str(uuid.uuid4())
    token = f"PLXI-{uuid.UUID(invite_id).hex}-{secrets.token_urlsafe(32)}"
    invitation = {"invite_id": invite_id, "token_hash": hashlib.sha256(token.encode()).hexdigest(),
                  "email": email, "license_id": str(uuid.uuid4()),
                  "created_at": now.isoformat(timespec="seconds"),
                  "expires_at": (now + timedelta(days=days)).isoformat(timespec="seconds")}
    record_store().create_named("invitations", invite_id, invitation)
    return {"token": token, "invitation": invitation_summary(invitation, None, False)}


def invitation_summary(invitation, record, revoked):
    expired = datetime.fromisoformat(invitation["expires_at"]) <= datetime.now(timezone.utc)
    status = "revoked" if revoked else "redeemed" if record else "expired" if expired else "ready"
    return {key: invitation[key] for key in ("invite_id", "email", "created_at", "expires_at")} | {
        "status": status, "customer": record["customer"] if record else "",
        "license_id": record["license_id"] if record else ""}


def invitation_history():
    store = record_store()
    with ThreadPoolExecutor(max_workers=3) as pool:
        invites, records, revocations = list(pool.map(store.list_named, ("invitations", "licenses", "revocations")))
    records = {record["license_id"]: record for record in records}
    revoked = {record["invite_id"] for record in revocations}
    return [invitation_summary(invite, records.get(invite["license_id"]), invite["invite_id"] in revoked)
            for invite in sorted(invites, key=lambda invite: invite["created_at"], reverse=True)]


def invitation_access(token):
    match = INVITE_TOKEN.fullmatch(token) if isinstance(token, str) else None
    if not match:
        raise InvitationError(403, "Enter a valid invitation code or use the link you received.")
    invite_id = str(uuid.UUID(match[1]))
    store = record_store()
    invitation = store.get_named("invitations", invite_id)
    if invitation is None or not hmac.compare_digest(invitation["token_hash"], hashlib.sha256(token.encode()).hexdigest()):
        raise InvitationError(403, "This invitation is not available. Check your code or contact Sustx Audio.")
    if store.get_named("revocations", invite_id):
        raise InvitationError(410, "This invitation has been revoked. Contact Sustx Audio.")
    record = store.get(invitation["license_id"])
    if record is None and datetime.fromisoformat(invitation["expires_at"]) <= datetime.now(timezone.utc):
        raise InvitationError(410, "This invitation has expired. Contact Sustx Audio for a new one.")
    return store, invitation, record


def redeem_invitation(data):
    store, invitation, existing = invitation_access(data.get("token"))
    email = email_address(data.get("email"))
    if invitation["email"] and not hmac.compare_digest(invitation["email"].encode(), email.encode()):
        raise InvitationError(403, "Use the email address this invitation was sent to.")
    # Validate all fields even for retries; the stored original always wins.
    document, _ = issue_license(data.get("customer"), data.get("request"), invitation["license_id"],
                                existing["issued_at"] if existing else None)
    candidate = make_record(document, "invitation", email, invitation["invite_id"])
    record = existing or store.create_named("licenses", invitation["license_id"], candidate)
    if record.get("invite_id") != invitation["invite_id"] or record.get("email") != email or record["machine"] != candidate["machine"]:
        raise InvitationError(409, "This invitation has already unlocked another computer. Contact Sustx Audio if you need help.")
    # A failed/retried download never issues another file. Revocation blocks link access.
    if store.get_named("revocations", invitation["invite_id"]):
        raise InvitationError(410, "This invitation has been revoked. Contact Sustx Audio.")
    verify_document(record["document"])
    return record["document"].encode(), f'Parallax-{record["license_id"]}.parallax-license'


class handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        # Never log credentials, request codes, or customer data.
        pass

    def reply(self, status, body, content_type="application/json; charset=utf-8", headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            session = read_session(self.headers.get("Cookie"))
            self.reply(200, {"authenticated": bool(session), "csrf": session["csrf"] if session else None})
        except ConfigurationError as error:
            self.reply(503, {"error": str(error)})

    def do_POST(self):
        # Same-origin JSON requests only; cookies alone cannot authorize issuance.
        scheme = "http" if local_mode() else "https"
        expected_origin = f"{scheme}://{self.headers.get('Host', '')}"
        if self.headers.get("Origin") != expected_origin or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.reply(403, {"error": "Open the private page on this website to continue."})
            return
        if self.headers.get_content_type() != "application/json":
            self.reply(415, {"error": "Expected a JSON request."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                self.reply(413, {"error": "Request is too large or empty."})
                return
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object.")
            encoded, secret = auth_settings()
            action = data.get("action")
            if action == "invite_status":
                _, invitation, record = invitation_access(data.get("token"))
                self.reply(200, {"status": "redeemed" if record else "ready"})
                return
            if action == "redeem":
                document, filename = redeem_invitation(data)
                self.reply(200, document, "application/octet-stream",
                           {"Content-Disposition": f'attachment; filename="{filename}"'})
                return
            if action == "login":
                password = data.get("password")
                if not isinstance(password, str) or len(password.encode()) > 1024:
                    raise ValueError("Enter your owner password.")
                if not hmac.compare_digest(password_hash(password, encoded.split("$")[2]), encoded):
                    self.reply(401, {"error": "That password did not match."})
                    return
                token, claims = session_token(secret, encoded)
                self.reply(200, {"authenticated": True, "csrf": claims["csrf"]},
                           headers={"Set-Cookie": session_cookie(token)})
                return
            session = read_session(self.headers.get("Cookie"))
            if not session:
                self.reply(401, {"error": "Sign in to generate a license."})
                return
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session["csrf"]):
                self.reply(403, {"error": "Refresh the page and try again."})
                return
            if action == "logout":
                self.reply(200, {"authenticated": False}, headers={"Set-Cookie": session_cookie("", 0)})
            elif action == "invite_create":
                self.reply(200, create_invitation(data))
            elif action == "invites":
                self.reply(200, {"invitations": invitation_history()})
            elif action == "invite_revoke":
                invite_id = canonical_id(data.get("invite_id"))
                store = record_store()
                if store.get_named("invitations", invite_id) is None:
                    self.reply(404, {"error": "That invitation is not in your records."})
                    return
                store.create_named("revocations", invite_id, {"invite_id": invite_id,
                                   "revoked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
                self.reply(200, {"revoked": True})
            elif action == "issue":
                document, filename = issue_license(data.get("customer"), data.get("request"))
                save_record(document, "issued")
                self.reply(200, document, "application/octet-stream",
                           {"Content-Disposition": f'attachment; filename="{filename}"'})
            elif action == "history":
                records = sorted(record_store().all(), key=lambda record: datetime.fromisoformat(record["issued_at"]).timestamp(), reverse=True)
                self.reply(200, {"records": [record_summary(record) for record in records]})
            elif action == "download":
                license_id = canonical_id(data.get("license_id"))
                record = record_store().get(license_id)
                if record is None:
                    self.reply(404, {"error": "That license is not in the history."})
                    return
                verify_document(record["document"])
                self.reply(200, record["document"].encode(), "application/octet-stream",
                           {"Content-Disposition": f'attachment; filename="Parallax-{license_id}.parallax-license"'})
            elif action == "export":
                records = sorted(record_store().all(), key=lambda record: datetime.fromisoformat(record["issued_at"]).timestamp(), reverse=True)
                self.reply(200, export_csv(records), "text/csv; charset=utf-8",
                           {"Content-Disposition": 'attachment; filename="Parallax-license-history.csv"'})
            elif action == "import":
                record = save_record(data.get("document"), "imported")
                self.reply(200, {"record": record_summary(record)})
            else:
                self.reply(400, {"error": "Unknown action."})
        except InvitationError as error:
            self.reply(error.status, {"error": str(error)})
        except ConfigurationError as error:
            self.reply(503, {"error": str(error)})
        except StorageError as error:
            self.reply(503, {"error": str(error)})
        except RecordConflict as error:
            self.reply(409, {"error": str(error)})
        except (ValueError, UnicodeError):
            self.reply(400, {"error": "Check the name, email address and complete request code."})
