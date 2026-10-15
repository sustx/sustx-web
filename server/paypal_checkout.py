"""Verified PayPal purchases and private, two-computer activation links."""
import base64
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import uuid

PRICE_CENTS = 5000
CURRENCY = "USD"
SEATS = 2
TOKEN = re.compile(r"PLXP-([0-9a-f]{32})-([A-Za-z0-9_-]{43})\Z")
CHECKOUT_KEY = re.compile(r"[0-9a-f]{64}\Z")
PAYPAL_ID = re.compile(r"[A-Z0-9]{8,64}\Z")
COLLECTIONS = ("purchases", "purchase_orders", "paypal_order_index", "payments",
               "payment_events", "email_deliveries", "email_limits")


class CheckoutError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def identifier(value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "audio.sustx.parallax/" + value))


def amount(cents):
    return f"{cents // 100}.{cents % 100:02d}"


def cents(value):
    try:
        number = Decimal(value)
        if not number.is_finite() or number < 0 or number * 100 != (number * 100).to_integral_value():
            raise ValueError()
        return int(number * 100)
    except (ValueError, TypeError, InvalidOperation):
        raise CheckoutError(502, "The payment amount could not be verified.") from None


def text(value, label, maximum, required=True):
    if not isinstance(value, str):
        raise CheckoutError(400, f"Enter {label}.")
    value = value.strip()
    if (required and not value) or len(value.encode()) > maximum or any(ord(c) < 32 for c in value):
        raise CheckoutError(400, f"Enter {label} using no more than {maximum} UTF-8 bytes.")
    return value


def email_address(value):
    value = text(value, "a valid email address", 254).lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise CheckoutError(400, "Enter a valid email address.")
    return value


def settings(local=False):
    mode = os.environ.get("PARALLAX_PAYPAL_ENV", "sandbox")
    origin = os.environ.get("PARALLAX_PUBLIC_ORIGIN", "https://www.sustx.xyz").rstrip("/")
    parsed = urlsplit(origin)
    valid_origin = (parsed.scheme == "https" or local and parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"})
    valid_origin = valid_origin and parsed.netloc and not parsed.path and not parsed.query and not parsed.fragment and not parsed.username
    values = {key: os.environ.get(key, "") for key in (
        "PARALLAX_PAYPAL_CLIENT_ID", "PARALLAX_PAYPAL_CLIENT_SECRET", "PARALLAX_PAYPAL_MERCHANT_ID",
        "PARALLAX_PAYPAL_WEBHOOK_ID", "PARALLAX_RESEND_API_KEY", "PARALLAX_EMAIL_FROM")}
    ready = (os.environ.get("PARALLAX_PAYPAL_ENABLED") == "1" and mode in {"sandbox", "live"}
             and valid_origin and all(values[key] for key in (
                 "PARALLAX_PAYPAL_CLIENT_ID", "PARALLAX_PAYPAL_CLIENT_SECRET",
                 "PARALLAX_PAYPAL_MERCHANT_ID", "PARALLAX_PAYPAL_WEBHOOK_ID")))
    # Production cannot accidentally sell sandbox licenses, or take money without
    # a recovery-email sender configured. Secrets never appear in public config.
    if os.environ.get("VERCEL_ENV") == "production" and mode != "live":
        ready = False
    if mode == "live" and not (values["PARALLAX_RESEND_API_KEY"] and values["PARALLAX_EMAIL_FROM"]):
        ready = False
    return {**values, "ready": bool(ready), "mode": mode, "origin": origin}


def quote(data):
    code = text(data.get("discount_code", ""), "a discount code", 40, required=False).upper()
    discount = 0
    if code:
        if not re.fullmatch(r"[A-Z0-9_-]+", code):
            raise CheckoutError(400, "That discount code is not available.")
        try:
            codes = json.loads(os.environ.get("PARALLAX_DISCOUNT_CODES_JSON", "{}"))
            entry = codes.get(code)
            if not isinstance(entry, dict) or entry.get("active", True) is not True:
                raise CheckoutError(400, "That discount code is not available.")
            if entry.get("expires_at"):
                expiry = datetime.fromisoformat(entry["expires_at"])
                if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                    raise CheckoutError(400, "That discount code has expired.")
            if set(entry) & {"percent_off", "amount_off_cents"} == {"percent_off"}:
                percent = entry["percent_off"]
                if type(percent) is not int or not 1 <= percent <= 99:
                    raise ValueError()
                discount = (PRICE_CENTS * percent + 50) // 100
            elif set(entry) & {"percent_off", "amount_off_cents"} == {"amount_off_cents"}:
                discount = entry["amount_off_cents"]
                if type(discount) is not int or not 1 <= discount <= PRICE_CENTS - 100:
                    raise ValueError()
            else:
                raise ValueError()
            if PRICE_CENTS - discount < 100:
                raise ValueError()
        except CheckoutError:
            raise
        except (ValueError, TypeError, AttributeError):
            raise CheckoutError(503, "Discounts are temporarily unavailable. Please try again.") from None
    return {"subtotal_cents": PRICE_CENTS, "discount_cents": discount,
            "total_cents": PRICE_CENTS - discount, "currency": CURRENCY, "discount_code": code}


def json_request(url, payload=None, headers=None, method=None, form=None):
    body = form if form is not None else json.dumps(payload).encode() if payload is not None else None
    request = Request(url, data=body, method=method,
                      headers={"Accept": "application/json", "Content-Type": "application/json",
                               "User-Agent": "Sustx-Parallax/1.0", **(headers or {})})
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except (HTTPError, URLError, OSError, ValueError):
        raise CheckoutError(502, "The payment service is temporarily unavailable. Please try again.") from None


class PayPalGateway:
    def __init__(self, config):
        self.config = config
        self.base = "https://api-m.paypal.com" if config["mode"] == "live" else "https://api-m.sandbox.paypal.com"
        self.access_token = None

    def request(self, method, path, payload=None, request_id=None):
        if self.access_token is None:
            credentials = self.config["PARALLAX_PAYPAL_CLIENT_ID"] + ":" + self.config["PARALLAX_PAYPAL_CLIENT_SECRET"]
            result = json_request(self.base + "/v1/oauth2/token", form=b"grant_type=client_credentials",
                                  headers={"Authorization": "Basic " + base64.b64encode(credentials.encode()).decode(),
                                           "Content-Type": "application/x-www-form-urlencoded"})
            self.access_token = result.get("access_token")
            if not self.access_token:
                raise CheckoutError(502, "The payment service is temporarily unavailable.")
        headers = {"Authorization": "Bearer " + self.access_token, "Prefer": "return=representation"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        return json_request(self.base + path, payload, headers, method=method)

    def create_order(self, purchase):
        price = purchase["price"]
        breakdown = {"item_total": {"currency_code": CURRENCY, "value": amount(PRICE_CENTS)}}
        if price["discount_cents"]:
            breakdown["discount"] = {"currency_code": CURRENCY, "value": amount(price["discount_cents"])}
        origin = self.config["origin"]
        return self.request("POST", "/v2/checkout/orders", {
            "intent": "CAPTURE",
            "purchase_units": [{"reference_id": purchase["purchase_id"], "custom_id": purchase["purchase_id"],
                "invoice_id": "PLX-" + purchase["purchase_id"], "description": "Parallax · two-computer perpetual license",
                "payee": {"merchant_id": self.config["PARALLAX_PAYPAL_MERCHANT_ID"]},
                "amount": {"currency_code": CURRENCY, "value": amount(price["total_cents"]), "breakdown": breakdown},
                "items": [{"name": "Parallax", "quantity": "1", "category": "DIGITAL_GOODS",
                           "unit_amount": {"currency_code": CURRENCY, "value": amount(PRICE_CENTS)}}]}],
            "payment_source": {"paypal": {"experience_context": {"brand_name": "Sustx Audio",
                "shipping_preference": "NO_SHIPPING", "user_action": "PAY_NOW",
                "return_url": origin + "/parallax/activate/?checkout=" + purchase["purchase_id"],
                "cancel_url": origin + "/parallax/checkout/?cancelled=1"}}}},
            "pc-" + uuid.UUID(purchase["purchase_id"]).hex)

    def get_order(self, order_id):
        if not PAYPAL_ID.fullmatch(order_id):
            raise CheckoutError(400, "Invalid payment reference.")
        return self.request("GET", "/v2/checkout/orders/" + order_id)

    def capture_order(self, order_id, purchase_id):
        if not PAYPAL_ID.fullmatch(order_id):
            raise CheckoutError(400, "Invalid payment reference.")
        return self.request("POST", "/v2/checkout/orders/" + order_id + "/capture", {}, "px-" + uuid.UUID(purchase_id).hex)

    def verify_webhook(self, event, headers):
        fields = {"auth_algo": "paypal-auth-algo", "cert_url": "paypal-cert-url",
                  "transmission_id": "paypal-transmission-id", "transmission_sig": "paypal-transmission-sig",
                  "transmission_time": "paypal-transmission-time"}
        values = {key: headers.get(header, "") for key, header in fields.items()}
        if not all(values.values()):
            raise CheckoutError(403, "Invalid payment notification.")
        result = self.request("POST", "/v1/notifications/verify-webhook-signature", {
            **values, "webhook_id": self.config["PARALLAX_PAYPAL_WEBHOOK_ID"], "webhook_event": event})
        if result.get("verification_status") != "SUCCESS":
            raise CheckoutError(403, "Invalid payment notification.")


class CheckoutService:
    def __init__(self, store, secret, issue, make_record, verify, local=False, gateway=None):
        self.store, self.secret = store, secret
        self.issue, self.make_record, self.verify = issue, make_record, verify
        self.config = settings(local)
        self.gateway = gateway or PayPalGateway(self.config)

    def require_ready(self):
        if not self.config["ready"]:
            raise CheckoutError(503, "Purchasing is currently unavailable. Please try again later.")

    def token(self, purchase_id):
        signature = base64.urlsafe_b64encode(hmac.digest(self.secret, ("purchase:" + purchase_id).encode(), "sha256")).rstrip(b"=").decode()
        return "PLXP-" + uuid.UUID(purchase_id).hex + "-" + signature

    def link(self, purchase_id):
        return self.config["origin"] + "/parallax/activate/#purchase=" + self.token(purchase_id)

    def access(self, token, paid=False):
        match = TOKEN.fullmatch(token) if isinstance(token, str) else None
        if not match:
            raise CheckoutError(403, "Use your private activation link or request it by email.")
        purchase_id = str(uuid.UUID(match[1]))
        if not hmac.compare_digest(token, self.token(purchase_id)):
            raise CheckoutError(403, "This activation link is not available.")
        purchase = self.store.get_named("purchases", purchase_id)
        if not purchase or not hmac.compare_digest(purchase["token_hash"], hashlib.sha256(token.encode()).hexdigest()):
            raise CheckoutError(403, "This activation link is not available.")
        payment = self.store.get_named("payments", purchase_id)
        if paid and not payment:
            raise CheckoutError(409, "Payment has not been confirmed yet. Please finish checkout first.")
        return purchase, payment

    def create(self, data):
        self.require_ready()
        checkout_key = data.get("checkout_key")
        if not isinstance(checkout_key, str) or not CHECKOUT_KEY.fullmatch(checkout_key):
            raise CheckoutError(400, "Refresh checkout and try again.")
        purchase_id = identifier("checkout:" + checkout_key)
        customer = text(data.get("customer"), "your name", 160)
        email = email_address(data.get("email"))
        referral = text(data.get("referral", ""), "a referral name or code", 120, required=False)
        price = quote(data)
        candidate = {"purchase_id": purchase_id, "customer": customer, "email": email, "price": price,
                     "referral": referral, "referral_source": "customer-provided", "created_at": now(),
                     "mode": self.config["mode"], "merchant_id": self.config["PARALLAX_PAYPAL_MERCHANT_ID"],
                     "seats": SEATS, "token_hash": hashlib.sha256(self.token(purchase_id).encode()).hexdigest()}
        purchase = self.store.create_named("purchases", purchase_id, candidate)
        if any(purchase[key] != candidate[key] for key in ("customer", "email", "price", "referral", "mode", "merchant_id")):
            raise CheckoutError(409, "Your checkout details changed. Refresh checkout and try again.")
        order = self.store.get_named("purchase_orders", purchase_id)
        if order is None:
            result = self.gateway.create_order(purchase)
            order_id = result.get("id", "")
            host = "www.paypal.com" if self.config["mode"] == "live" else "www.sandbox.paypal.com"
            approval = next((link.get("href", "") for link in result.get("links", []) if link.get("rel") in {"payer-action", "approve"}), "")
            url = urlsplit(approval)
            if not PAYPAL_ID.fullmatch(order_id) or url.scheme != "https" or url.hostname != host or url.username:
                raise CheckoutError(502, "PayPal checkout could not be opened. Please try again.")
            order = self.store.create_named("purchase_orders", purchase_id,
                                           {"purchase_id": purchase_id, "order_id": order_id, "approval_url": approval})
        self.store.create_named("paypal_order_index", identifier(self.config["mode"] + ":" + order["order_id"]),
                                {"purchase_id": purchase_id, "order_id": order["order_id"]})
        return {"purchase_id": purchase_id, "token": self.token(purchase_id), "approval_url": order["approval_url"], "price": price}

    def settle(self, purchase, result):
        stored = self.store.get_named("purchase_orders", purchase["purchase_id"])
        try:
            unit, = result["purchase_units"]
            capture, = unit["payments"]["captures"]
            if (not stored or result["id"] != stored["order_id"] or result["status"] != "COMPLETED"
                    or capture["status"] != "COMPLETED" or not PAYPAL_ID.fullmatch(capture["id"])
                    or unit["custom_id"] != purchase["purchase_id"]
                    or unit["payee"]["merchant_id"] != purchase["merchant_id"]
                    or capture["amount"]["currency_code"] != CURRENCY
                    or cents(capture["amount"]["value"]) != purchase["price"]["total_cents"]):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise CheckoutError(409, "This payment is not confirmed for your purchase. Please contact Sustx Audio.") from None
        payer = result.get("payer", result.get("payment_source", {}).get("paypal", {}))
        breakdown = capture.get("seller_receivable_breakdown", {})
        candidate = {"purchase_id": purchase["purchase_id"], "order_id": stored["order_id"],
                     "capture_id": capture["id"], "status": "COMPLETED", "paid_at": capture.get("create_time", now()),
                     "amount_cents": purchase["price"]["total_cents"], "currency": CURRENCY,
                     "payer_id": payer.get("payer_id", payer.get("account_id", "")),
                     "payer_email": payer.get("email_address", ""),
                     "payer_name": payer.get("name", {}), "payer_country": payer.get("address", {}).get("country_code", ""),
                     "paypal_fee_cents": cents(breakdown["paypal_fee"]["value"]) if breakdown.get("paypal_fee") else None,
                     "net_cents": cents(breakdown["net_amount"]["value"]) if breakdown.get("net_amount") else None,
                     "verified_at": now(), "mode": purchase["mode"]}
        payment = self.store.create_named("payments", purchase["purchase_id"], candidate)
        if payment["capture_id"] != candidate["capture_id"]:
            raise CheckoutError(409, "This purchase already has a different payment reference.")
        return payment

    def capture(self, data):
        self.require_ready()
        purchase, payment = self.access(data.get("token"))
        if purchase["mode"] != self.config["mode"] or purchase["merchant_id"] != self.config["PARALLAX_PAYPAL_MERCHANT_ID"]:
            raise CheckoutError(409, "This purchase belongs to a different checkout environment.")
        if payment is None:
            stored = self.store.get_named("purchase_orders", purchase["purchase_id"])
            if stored is None:
                raise CheckoutError(409, "Please finish checkout first.")
            order = self.gateway.get_order(stored["order_id"])
            if order.get("status") != "COMPLETED":
                if order.get("status") != "APPROVED":
                    raise CheckoutError(409, "Payment has not been approved. Please finish PayPal checkout first.")
                try:
                    order = self.gateway.capture_order(stored["order_id"], purchase["purchase_id"])
                except CheckoutError:
                    # Recover a successful capture whose response was interrupted.
                    order = self.gateway.get_order(stored["order_id"])
            payment = self.settle(purchase, order)
        self.send_email(purchase)
        return self.status(data)

    def activations(self, purchase):
        records = []
        for seat in range(purchase["seats"]):
            record = self.store.get(identifier(f'{purchase["purchase_id"]}:seat:{seat}'))
            if record:
                records.append(record)
        return records

    def status(self, data):
        purchase, payment = self.access(data.get("token"))
        records = self.activations(purchase) if payment else []
        return {"purchase_id": purchase["purchase_id"], "customer": purchase["customer"], "email": purchase["email"],
                "paid": bool(payment), "price": purchase["price"], "seats": purchase["seats"], "mode": purchase["mode"],
                "remaining": purchase["seats"] - len(records), "paid_at": payment["paid_at"] if payment else "",
                "activations": [{key: record[key] for key in ("license_id", "platform", "machine", "issued_at")} for record in records]}

    def redeem(self, data):
        purchase, payment = self.access(data.get("token"), paid=True)
        request = data.get("request")
        # Validate the request with the native license issuer before reserving a seat.
        self.issue(purchase["customer"], request, identifier(purchase["purchase_id"] + ":validation"))
        for seat in range(purchase["seats"]):
            license_id = identifier(f'{purchase["purchase_id"]}:seat:{seat}')
            existing = self.store.get(license_id)
            if existing is not None:
                if existing["machine"] == request.strip():
                    return self.download(data | {"license_id": license_id})
                continue
            document, _ = self.issue(purchase["customer"], request, license_id)
            candidate = self.make_record(document, "purchase", purchase["email"])
            candidate.update({"purchase_id": purchase["purchase_id"], "seat": seat + 1,
                              "amount_cents": payment["amount_cents"], "currency": CURRENCY,
                              "referral": purchase["referral"], "discount_code": purchase["price"]["discount_code"]})
            record = self.store.create_named("licenses", license_id, candidate)
            if record["machine"] == request.strip():
                return self.download(data | {"license_id": license_id})
        raise CheckoutError(409, "Both computers are already activated. You can download their licenses below, or contact Sustx Audio for help.")

    def download(self, data):
        purchase, _ = self.access(data.get("token"), paid=True)
        record = next((record for record in self.activations(purchase) if record["license_id"] == data.get("license_id")), None)
        if record is None:
            raise CheckoutError(404, "That license does not belong to this purchase.")
        self.verify(record["document"])
        return record["document"].encode(), f'Parallax-{record["license_id"]}.parallax-license'

    def send_email(self, purchase, purpose="initial"):
        key = identifier(purchase["purchase_id"] + ":email:" + purpose)
        if self.store.get_named("email_deliveries", key):
            return True
        api_key = self.config["PARALLAX_RESEND_API_KEY"]
        sender = self.config["PARALLAX_EMAIL_FROM"]
        if not api_key or not sender:
            return False
        try:
            result = json_request("https://api.resend.com/emails", {
                "from": sender, "to": [purchase["email"]], "subject": "Your Parallax activation link",
                "text": f'Hi {purchase["customer"]},\n\nYour Parallax purchase is ready. '
                        f'You paid ${amount(purchase["price"]["total_cents"])} USD.\n\n'
                        f'Activate up to {purchase["seats"]} computers and download your licenses here:\n'
                        f'{self.link(purchase["purchase_id"])}\n\n'
                        f'Download Parallax: {self.config["origin"]}/parallax/\n\n'
                        'Keep this private link for future activations and downloads.\n\nSustx Audio\n'},
                {"Authorization": "Bearer " + api_key, "Idempotency-Key": "parallax-" + key})
            if not isinstance(result.get("id"), str):
                return False
            self.store.create_named("email_deliveries", key, {"purchase_id": purchase["purchase_id"],
                "email": purchase["email"], "sent_at": now(), "message_id": result["id"], "purpose": purpose})
            return True
        except CheckoutError:
            return False

    def recovery(self, data, client="", owner=False):
        email = email_address(data.get("email"))
        # A uniform response prevents searching the customer database anonymously.
        reply = {"message": "If a paid purchase matches that email, its activation link will be sent shortly."}
        bucket = str(int(time.time()) // 600)
        scopes = ["email:" + email]
        if not owner and client and client != "unknown":
            scopes.append("client:" + client)
        for scope in scopes:
            key = identifier("recovery:" + bucket + ":" + hmac.new(self.secret, scope.encode(), "sha256").hexdigest())
            nonce = secrets.token_hex(16)
            entry = self.store.create_named("email_limits", key, {"nonce": nonce, "created_at": now()})
            if entry["nonce"] != nonce:
                return reply
        for purchase in self.store.list_named("purchases"):
            if purchase["email"] == email and self.store.get_named("payments", purchase["purchase_id"]):
                self.send_email(purchase, "recovery:" + bucket)
        return reply

    def webhook(self, event, headers):
        self.require_ready()
        self.gateway.verify_webhook(event, headers)
        event_id = event.get("id")
        if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", event_id):
            raise CheckoutError(400, "Invalid payment notification.")
        key = identifier(self.config["mode"] + ":event:" + event_id)
        if self.store.get_named("payment_events", key):
            return {"received": True}
        event_type = event.get("event_type")
        if event_type != "PAYMENT.CAPTURE.COMPLETED":
            return {"received": True}
        order_id = event.get("resource", {}).get("supplementary_data", {}).get("related_ids", {}).get("order_id", "")
        if not isinstance(order_id, str) or not PAYPAL_ID.fullmatch(order_id):
            raise CheckoutError(400, "Invalid payment notification.")
        index = self.store.get_named("paypal_order_index", identifier(self.config["mode"] + ":" + order_id))
        if index is None:
            # Events for other products on the same PayPal account are unrelated.
            return {"received": True}
        purchase = self.store.get_named("purchases", index["purchase_id"])
        if purchase["mode"] != self.config["mode"] or purchase["merchant_id"] != self.config["PARALLAX_PAYPAL_MERCHANT_ID"]:
            raise CheckoutError(409, "Payment environment mismatch.")
        self.settle(purchase, self.gateway.get_order(order_id))
        if not self.send_email(purchase):
            raise CheckoutError(503, "Activation email delivery is pending. Retry this notification.")
        self.store.create_named("payment_events", key, {"event_id": event_id, "event_type": event_type,
            "purchase_id": purchase["purchase_id"], "order_id": order_id, "processed_at": now()})
        return {"received": True}

    def sales(self):
        purchases = {item["purchase_id"]: item for item in self.store.list_named("purchases")}
        result = []
        for payment in self.store.list_named("payments"):
            purchase = purchases[payment["purchase_id"]]
            records = self.activations(purchase)
            result.append({**{key: purchase[key] for key in ("purchase_id", "customer", "email", "created_at", "referral", "seats")},
                           **payment, "price": purchase["price"], "activated": len(records),
                           "license_ids": [record["license_id"] for record in records]})
        return sorted(result, key=lambda row: row["paid_at"], reverse=True)
