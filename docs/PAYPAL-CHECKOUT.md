# Parallax purchases with PayPal

Parallax is a one-time **$50 USD purchase with two computer activations**.
The Buy button becomes active only when the payment integration is configured
and explicitly enabled. No production credentials or discount codes are created
by this change.

## Customer sequence

1. `/parallax/checkout/` requires a name and email address. Optional fields accept
   a discount code and a referral name/code. A `?ref=CODE` link can prefill referral.
2. The server calculates the price, creates a PayPal order and saves the customer,
   amount, discount and referral in private storage before leaving the website.
3. PayPal opens its payment page. Shipping collection is disabled for this digital
   product. Available payment methods and guest checkout are determined by PayPal.
4. PayPal returns to `/parallax/activate/?checkout=PURCHASE_ID`. The browser recovers
   its private capability from session storage or a Secure, HttpOnly, SameSite=Lax
   checkout cookie, and asks the server to capture/verify the order. The public
   purchase ID alone grants no access.
5. A completed capture must match the stored order, purchase ID, merchant ID,
   currency and server-calculated amount before activation is allowed.
6. The customer sees their name, email, amount paid and remaining computer slots
   as read-only text. The only entry field is the plug-in request code. Paying
   customers never see an invitation-code field or invitation terminology.
7. Each distinct computer consumes one slot. Reusing that computer's request code
   returns the byte-identical original license. Conditional record creation limits
   concurrent requests to two slots. AU and VST3 share the same Mac request code.
8. An activation email links back to this page. Customers can copy the private
   link, email it again, use it on a second computer, or redownload either license.

The email link stores its capability in the URL fragment, which is not sent in
HTTP requests or referrers. Links are derived with a domain-separated HMAC from
the existing release signing key. Rotating the owner-session secret does not
invalidate purchase links. Preserve the existing release signing key and backup.

## Configure PayPal and activation email

Confirm that the seller has a PayPal **Business** account. In the
[PayPal developer dashboard](https://developer.paypal.com/dashboard/applications),
create a REST app. Start with sandbox seller and buyer accounts. The merchant ID
must belong to the receiving seller account for the selected environment.

Set these server-side environment variables in the existing `sustx-web` Vercel
project. Use Sensitive variables for credentials. Never put secrets in frontend
JavaScript, Git, or chat.

| Variable | Value |
| --- | --- |
| `PARALLAX_PAYPAL_ENABLED` | `1` to enable purchasing; absent/`0` leaves it unavailable |
| `PARALLAX_PAYPAL_ENV` | `sandbox` or `live`; default is sandbox |
| `PARALLAX_PAYPAL_CLIENT_ID` | REST app client ID for that environment |
| `PARALLAX_PAYPAL_CLIENT_SECRET` | REST app secret for that environment |
| `PARALLAX_PAYPAL_MERCHANT_ID` | Receiving seller's PayPal merchant ID |
| `PARALLAX_PAYPAL_WEBHOOK_ID` | Webhook registration ID for that REST app/environment |
| `PARALLAX_PUBLIC_ORIGIN` | `https://www.sustx.xyz` in production |
| `PARALLAX_RESEND_API_KEY` | Resend sending API key for activation emails |
| `PARALLAX_EMAIL_FROM` | Sender on a verified domain, e.g. `Sustx Audio <licenses@YOUR_DOMAIN>` |
| `PARALLAX_DISCOUNT_CODES_JSON` | Optional server-side discount definitions; defaults to `{}` |

Existing license signing, private-record storage and owner-access variables stay
configured as documented in `PARALLAX.md`. Production refuses to enable sandbox
checkout and refuses live checkout without an activation-email sender configured.
The checkout can be tested in a Vercel preview deployment with sandbox variables.

Register this webhook URL in the PayPal app:

```text
https://www.sustx.xyz/api/parallax?paypal_webhook=1
```

Subscribe to `PAYMENT.CAPTURE.COMPLETED`. Use the preview deployment URL when
testing in sandbox. The listener verifies notifications through PayPal's
`verify-webhook-signature` API using the configured webhook ID, then retrieves the
order from PayPal to verify the payment independently of the posted event body.
Webhook retries also recover activation email delivery after a browser closes.

PayPal captures and email sends use idempotency keys. A successful capture whose
HTTP response or storage write was interrupted is recovered from the order's
current status without charging again. A confirmed payment is retained even if
email delivery fails, so its activation page can still work while a webhook retry
delivers the email.

For local testing, add PayPal settings to the existing ignored
`.private/parallax-env.json` file, then run `python3 scripts/serve_parallax.py`.
Use sandbox credentials and an origin such as `http://127.0.0.1:8080`; never enable
live payment credentials in an automated test fixture. Automated tests replace
the provider and email service with fakes and use an unrelated signing key.

## Discounts and referrals

Discount generation/admin editing is intentionally deferred. With the default
empty configuration, unknown codes are rejected rather than silently ignored.
The backend supports a configured code with either integer `percent_off` (1–99)
or integer `amount_off_cents`, plus optional `active` and timezone-aware
`expires_at`. Codes are case-insensitive. Minimum checkout total is $1; free
licenses can continue to use the existing invitation system. There are no
single-use or campaign redemption limits in this version.

Referral is optional, stored exactly as entered after trimming/validation, and
marked as customer-provided attribution. It does not apply a discount, establish
an affiliate identity, calculate commission, or issue payouts. Referral codes
and affiliate management can be added later without losing existing attribution.

## Private purchase records and recovery

The existing private Blob store persists purchases, PayPal order mappings,
verified captures, webhook receipts, email delivery receipts and recovery limits.
Local preview/testing uses the same record interface backed by SQLite.

Each purchase records its customer name/email, referral, full price, discount,
amount paid, currency, environment, creation/payment dates, PayPal order/capture
IDs, payer identity/email/country and PayPal fee/net amounts when supplied.
Licenses link back to the purchase and their computer slot. Card numbers and
payment credentials are not collected or stored by this website.

The owner desk adds **Paid purchases** with search by customer, email, referral or
payment reference; sales CSV export; a private-link copy action; and email resend.
Purchases are recorded before activation, so a buyer is visible even if they have
not generated a license yet. License history labels these records as paid
purchases. Sales CSV has one row per purchase; license CSV has one row per computer.

`/parallax/recover/` sends the same generic response for known and unknown emails.
Recovery emails are throttled per recipient and client for ten-minute windows.
Recovery reuses the existing paid link; it does not create a new purchase, reset
computer slots, or generate replacement licenses.

## Before accepting real payments

Run a real PayPal sandbox purchase with the configured seller/buyer accounts and
verified sender, including cancellation, return, webhook-only completion and email
recovery. Then use the live app's credentials, merchant ID and webhook registration.
The current price calculation does not automate sales-tax calculation, filing or
remittance; settle the applicable tax treatment before enabling live checkout.
Refund/dispute handling remains in PayPal. This update does not automate a refund
policy or revoke already-issued offline licenses.

References: [PayPal Orders integration](https://developer.paypal.com/checkout/put-it-all-together/),
[PayPal webhook verification](https://developer.paypal.com/api/rest/webhooks/rest/),
[Resend email API](https://resend.com/docs/api-reference/emails/send-email).
