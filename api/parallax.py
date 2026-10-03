"""Owner-only Parallax issuer. Secrets are read from server environment variables."""
import base64
from datetime import datetime, timezone
import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import re
import secrets
import time
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "audio.sustx.parallax.beta"  # Existing plug-in protocol ID; never displayed.
REQUEST = re.compile(r"PLX1-(?:MAC|WIN)-[0-9a-f]{64}\Z")
SESSION_SECONDS = 8 * 60 * 60
MAX_BODY = 4096


class ConfigurationError(Exception):
    pass


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


def issue_license(customer, request):
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
    license_id = str(uuid.uuid4())
    payload = json.dumps({"schema": 1, "product": PRODUCT, "license_id": license_id,
                          "customer": customer, "machine": request, "perpetual": True,
                          "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    document = json.dumps({"payload": base64.b64encode(payload).decode(),
                           "signature": key.sign(payload).hex()}, indent=2).encode() + b"\n"
    return document, f"Parallax-{license_id}.parallax-license"


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
            elif action == "issue":
                document, filename = issue_license(data.get("customer"), data.get("request"))
                self.reply(200, document, "application/octet-stream",
                           {"Content-Disposition": f'attachment; filename="{filename}"'})
            else:
                self.reply(400, {"error": "Unknown action."})
        except ConfigurationError as error:
            self.reply(503, {"error": str(error)})
        except (ValueError, UnicodeError):
            self.reply(400, {"error": "Check the customer name and complete request code."})
