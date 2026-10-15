"""Checkout integration checks use test keys and a fake PayPal gateway only."""
from concurrent.futures import ThreadPoolExecutor
import copy
import csv
import hashlib
import io
import json
import os
import secrets
import unittest
from unittest.mock import patch

import test_parallax as fixtures
from server import paypal_checkout as payments

api = fixtures.api
RealGateway = payments.PayPalGateway


class FakePayPal:
    def __init__(self):
        self.orders = {}
        self.captures = 0
        self.create_calls = 0
        self.fail_after_capture = False

    def create_order(self, purchase):
        self.create_calls += 1
        order_id = 'ORDER' + purchase['purchase_id'].replace('-', '').upper()[:20]
        self.orders.setdefault(order_id, {
            'id': order_id, 'status': 'PAYER_ACTION_REQUIRED',
            'payer': {'payer_id': 'PAYER123456', 'email_address': 'paypal-payer@example.com',
                      'name': {'given_name': 'PayPal', 'surname': 'Buyer'}, 'address': {'country_code': 'US'}},
            'purchase_units': [{'custom_id': purchase['purchase_id'], 'payee': {'merchant_id': 'MERCHANT12345'},
                'amount': {'currency_code': 'USD', 'value': payments.amount(purchase['price']['total_cents'])}}],
        })
        return {'id': order_id, 'links': [{'rel': 'payer-action', 'href': 'https://www.sandbox.paypal.com/checkoutnow?token=' + order_id}]}

    def get_order(self, order_id):
        return copy.deepcopy(self.orders[order_id])

    def capture_order(self, order_id, purchase_id):
        order = self.orders[order_id]
        if order['status'] != 'COMPLETED':
            self.captures += 1
            order['status'] = 'COMPLETED'
            value = order['purchase_units'][0]['amount']['value']
            order['purchase_units'][0]['payments'] = {'captures': [{
                'id': 'CAPTURE' + purchase_id.replace('-', '').upper()[:18], 'status': 'COMPLETED',
                'amount': {'currency_code': 'USD', 'value': value}, 'create_time': payments.now(),
                'seller_receivable_breakdown': {'paypal_fee': {'currency_code': 'USD', 'value': '2.24'},
                                                'net_amount': {'currency_code': 'USD', 'value': payments.amount(payments.cents(value) - 224)}}}]}
        if self.fail_after_capture:
            self.fail_after_capture = False
            raise payments.CheckoutError(502, 'Simulated interrupted response')
        return copy.deepcopy(order)

    def verify_webhook(self, event, headers):
        if headers.get('paypal-transmission-sig') != 'test-valid':
            raise payments.CheckoutError(403, 'Invalid payment notification.')


class CheckoutTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.LicenseApiTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.LicenseApiTests.tearDownClass.__func__)
    call = fixtures.LicenseApiTests.call
    login = fixtures.LicenseApiTests.login

    def setUp(self):
        fixtures.LicenseApiTests.setUp(self)
        self.gateway = FakePayPal()
        self.email_calls = []
        self.config = patch.dict(os.environ, {
            'PARALLAX_PAYPAL_ENABLED': '1', 'PARALLAX_PAYPAL_ENV': 'sandbox',
            'PARALLAX_PUBLIC_ORIGIN': self.origin, 'PARALLAX_PAYPAL_CLIENT_ID': 'test-client',
            'PARALLAX_PAYPAL_CLIENT_SECRET': 'test-secret', 'PARALLAX_PAYPAL_MERCHANT_ID': 'MERCHANT12345',
            'PARALLAX_PAYPAL_WEBHOOK_ID': 'test-webhook', 'PARALLAX_RESEND_API_KEY': 'test-mail',
            'PARALLAX_EMAIL_FROM': 'Sustx Audio <test@example.com>', 'VERCEL_ENV': '',
            'PARALLAX_DISCOUNT_CODES_JSON': json.dumps({'TEST10': {'percent_off': 10}, 'TEST5': {'amount_off_cents': 500}}),
        })
        self.config.start(); self.addCleanup(self.config.stop)
        gateway_patch = patch.object(payments, 'PayPalGateway', return_value=self.gateway)
        gateway_patch.start(); self.addCleanup(gateway_patch.stop)
        def mail(url, payload=None, headers=None, **kwargs):
            self.assertEqual(url, 'https://api.resend.com/emails')
            self.email_calls.append((copy.deepcopy(payload), dict(headers or {})))
            return {'id': 'test-email-id'}
        email_patch = patch.object(payments, 'json_request', side_effect=mail)
        email_patch.start(); self.addCleanup(email_patch.stop)

    def json_call(self, data, status=200, cookie=None, csrf=None):
        code, headers, body = self.call(data, cookie, csrf)
        self.assertEqual(code, status, body.decode(errors='replace'))
        return json.loads(body), headers

    def create(self, **overrides):
        data = {'action': 'checkout_create', 'customer': 'Paid Customer', 'email': 'buyer@example.com',
                'checkout_key': secrets.token_hex(32), 'discount_code': '', 'referral': 'Producer Alice'}
        data.update(overrides)
        result, headers = self.json_call(data)
        result['_request'] = data
        result['_cookie'] = headers['Set-Cookie'].split(';')[0]
        return result

    def paid(self, **overrides):
        checkout = self.create(**overrides)
        stored = api.record_store().get_named('purchase_orders', checkout['purchase_id'])
        self.gateway.orders[stored['order_id']]['status'] = 'APPROVED'
        result, _ = self.json_call({'action': 'checkout_capture', 'token': checkout['token']})
        self.assertTrue(result['paid'])
        return checkout

    def redeem(self, checkout, request, status=200, **overrides):
        response = self.call({'action': 'purchase_redeem', 'token': checkout['token'], 'request': request, **overrides})
        self.assertEqual(response[0], status, response[2].decode(errors='replace'))
        return response

    def test_preview_signing_key_is_required_and_cannot_override_production(self):
        real_public = api.release_public_key()
        with patch.dict(os.environ, {'VERCEL_ENV': 'preview', 'PARALLAX_SANDBOX_PUBLIC_KEY': 'a' * 64}):
            self.assertEqual(api.release_public_key(), 'a' * 64)
        with patch.dict(os.environ, {'VERCEL_ENV': 'production', 'PARALLAX_SANDBOX_PUBLIC_KEY': 'a' * 64}):
            self.assertEqual(api.release_public_key(), real_public)
        with patch.dict(os.environ, {'VERCEL_ENV': 'preview', 'PARALLAX_SANDBOX_PUBLIC_KEY': ''}):
            with self.assertRaises(api.ConfigurationError):
                api.release_public_key()

    def test_discount_cannot_reduce_total_below_one_dollar(self):
        with patch.dict(os.environ, {'PARALLAX_DISCOUNT_CODES_JSON': json.dumps({'TOOLOW': {'percent_off': 99}})}):
            self.json_call({'action': 'checkout_quote', 'discount_code': 'TOOLOW'}, 503)

    def test_config_has_no_secrets_and_production_requires_live_email(self):
        config, _ = self.json_call({'action': 'checkout_config'})
        self.assertTrue(config['ready']); self.assertEqual(config['seats'], 2)
        self.assertEqual(set(config), {'ready', 'mode', 'price', 'seats'})
        with patch.dict(os.environ, {'PARALLAX_PAYPAL_ENABLED': '0'}):
            self.assertFalse(self.json_call({'action': 'checkout_config'})[0]['ready'])
            self.json_call({'action': 'checkout_create'}, 503)
        with patch.dict(os.environ, {'VERCEL_ENV': 'production'}):
            self.assertFalse(self.json_call({'action': 'checkout_config'})[0]['ready'])
        with patch.dict(os.environ, {'PARALLAX_PAYPAL_ENV': 'live', 'PARALLAX_RESEND_API_KEY': ''}):
            self.assertFalse(self.json_call({'action': 'checkout_config'})[0]['ready'])

    def test_name_email_and_codes_validated_and_price_is_server_owned(self):
        for overrides in ({'customer': ''}, {'customer': 'x\ny'}, {'email': ''}, {'email': 'invalid'}, {'discount_code': 'FAKE'}, {'checkout_key': 'bad'}):
            data = {'action': 'checkout_create', 'customer': 'Buyer', 'email': 'buyer@example.com', 'checkout_key': secrets.token_hex(32)} | overrides
            self.json_call(data, 400)
        checkout = self.create(total_cents=1, amount='0.01', price={'total_cents': 1})
        self.assertEqual(checkout['price']['total_cents'], 5000)
        self.assertEqual(self.gateway.create_calls, 1)
        again, _ = self.json_call(checkout['_request'])
        self.assertEqual(again['token'], checkout['token'])
        self.assertEqual(self.gateway.create_calls, 1)
        self.json_call(checkout['_request'] | {'customer': 'Other'}, 409)

    def test_discount_quote_and_referral_are_persisted(self):
        for code in ['test10', 'TEST5']:
            checkout = self.paid(discount_code=code)
            self.assertEqual(checkout['price']['total_cents'], 4500)
            purchase = api.record_store().get_named('purchases', checkout['purchase_id'])
            self.assertEqual(purchase['price']['discount_code'], code.upper())
            self.assertEqual(purchase['referral'], 'Producer Alice')
            self.assertEqual(purchase['email'], 'buyer@example.com')
        with patch.dict(os.environ, {'PARALLAX_DISCOUNT_CODES_JSON': '{}'}):
            self.json_call({'action': 'checkout_quote', 'discount_code': 'TEST10'}, 400)

    def test_unpaid_or_forged_tokens_cannot_generate_or_access_data(self):
        checkout = self.create()
        self.redeem(checkout, self.request_code, 409)
        self.json_call({'action': 'purchase_status', 'token': checkout['token'][:-1] + '!'}, 403)
        self.json_call({'action': 'checkout_capture', 'token': checkout['token']}, 409)
        self.assertEqual(api.record_store().all(), [])
        self.json_call({'action': 'checkout_resume', 'purchase_id': checkout['purchase_id']}, 403)
        result, _ = self.json_call({'action': 'checkout_resume', 'purchase_id': checkout['purchase_id']}, cookie=checkout['_cookie'])
        self.assertEqual(result['token'], checkout['token'])
        self.json_call({'action': 'checkout_resume', 'purchase_id': '00000000-0000-0000-0000-000000000000'}, 403, cookie=checkout['_cookie'])

    def test_two_computers_then_repeated_downloads_and_readonly_identity(self):
        checkout = self.paid()
        first = self.redeem(checkout, self.request_code, customer='Attacker name', email='other@example.com')[2]
        self.assertEqual(api.verify_document(first.decode())['customer'], 'Paid Customer')
        second_code = 'PLX1-WIN-' + 'b' * 64
        second = self.redeem(checkout, second_code)[2]
        self.assertNotEqual(first, second)
        self.assertEqual(self.redeem(checkout, self.request_code)[2], first)
        self.assertEqual(self.redeem(checkout, second_code)[2], second)
        self.redeem(checkout, 'PLX1-MAC-' + 'c' * 64, 409)
        status, _ = self.json_call({'action': 'purchase_status', 'token': checkout['token']})
        self.assertEqual(status['remaining'], 0)
        self.assertEqual(status['email'], 'buyer@example.com')
        self.assertEqual(len(status['activations']), 2)
        for record in api.record_store().all():
            self.assertEqual(record['source'], 'purchase')
            self.assertEqual(record['purchase_id'], checkout['purchase_id'])
            self.assertEqual(record['amount_cents'], 5000)
            self.assertEqual(record['email'], 'buyer@example.com')
        other = self.paid(email='second@example.com')
        license_id = status['activations'][0]['license_id']
        self.json_call({'action': 'purchase_download', 'token': other['token'], 'license_id': license_id}, 404)
        downloaded = self.call({'action': 'purchase_download', 'token': checkout['token'], 'license_id': license_id})
        self.assertEqual(downloaded[2], first)

    def test_concurrent_redemptions_cannot_exceed_two_computers(self):
        checkout = self.paid()
        codes = ['PLX1-MAC-' + str(i) * 64 for i in range(1, 7)]
        def redeem(code):
            return self.call({'action': 'purchase_redeem', 'token': checkout['token'], 'request': code})
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(redeem, codes))
        self.assertEqual(sorted(result[0] for result in results), [200, 200, 409, 409, 409, 409])
        self.assertEqual(len(api.record_store().all()), 2)

    def test_same_machine_race_uses_one_seat(self):
        checkout = self.paid()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.call({'action': 'purchase_redeem', 'token': checkout['token'], 'request': self.request_code}), range(4)))
        self.assertTrue(all(result[0] == 200 for result in results))
        self.assertEqual(len({result[2] for result in results}), 1)
        self.assertEqual(len(api.record_store().all()), 1)

    def test_capture_retries_never_charge_or_email_twice(self):
        self.gateway.fail_after_capture = True
        checkout = self.paid()
        self.json_call({'action': 'checkout_capture', 'token': checkout['token']})
        self.assertEqual(self.gateway.captures, 1)
        self.assertEqual(len(api.record_store().list_named('payments')), 1)
        self.assertEqual(len(self.email_calls), 1)
        email = self.email_calls[0][0]
        self.assertEqual(email['to'], ['buyer@example.com'])
        self.assertIn('#purchase=' + checkout['token'], email['text'])
        self.assertNotIn('invitation', email['text'].lower())

    def test_completed_capture_must_match_amount_currency_merchant_and_purchase(self):
        for field in ['amount', 'currency', 'merchant', 'purchase', 'status']:
            checkout = self.create()
            order_id = api.record_store().get_named('purchase_orders', checkout['purchase_id'])['order_id']
            self.gateway.orders[order_id]['status'] = 'APPROVED'
            self.gateway.capture_order(order_id, checkout['purchase_id'])
            order = self.gateway.orders[order_id]
            unit = order['purchase_units'][0]
            capture = unit['payments']['captures'][0]
            if field == 'amount': capture['amount']['value'] = '0.01'
            elif field == 'currency': capture['amount']['currency_code'] = 'EUR'
            elif field == 'merchant': unit['payee']['merchant_id'] = 'OTHER123456'
            elif field == 'purchase': unit['custom_id'] = 'wrong-purchase'
            else: capture['status'] = 'PENDING'
            self.json_call({'action': 'checkout_capture', 'token': checkout['token']}, 409)
            self.assertIsNone(api.record_store().get_named('payments', checkout['purchase_id']))

    def test_storage_failure_after_capture_allows_recovery_without_recharge(self):
        checkout = self.create()
        order_id = api.record_store().get_named('purchase_orders', checkout['purchase_id'])['order_id']
        self.gateway.orders[order_id]['status'] = 'APPROVED'
        original = api.LocalRecords.create_named
        def broken(store, kind, key, value):
            if kind == 'payments': raise api.StorageError('Unavailable')
            return original(store, kind, key, value)
        with patch.object(api.LocalRecords, 'create_named', broken):
            self.json_call({'action': 'checkout_capture', 'token': checkout['token']}, 503)
        self.assertEqual(self.gateway.captures, 1)
        self.json_call({'action': 'checkout_capture', 'token': checkout['token']})
        self.assertEqual(self.gateway.captures, 1)

    def test_webhooks_require_signature_and_are_idempotent(self):
        checkout = self.create()
        order_id = api.record_store().get_named('purchase_orders', checkout['purchase_id'])['order_id']
        self.gateway.orders[order_id]['status'] = 'APPROVED'
        self.gateway.capture_order(order_id, checkout['purchase_id'])
        event = {'id': 'WEBHOOK-EVENT-1234', 'event_type': 'PAYMENT.CAPTURE.COMPLETED',
                 'resource': {'supplementary_data': {'related_ids': {'order_id': order_id}}}}
        import http.client
        def send(signature):
            connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
            connection.request('POST', '/api/parallax?paypal_webhook=1', json.dumps(event),
                               {'Content-Type': 'application/json', 'PAYPAL-TRANSMISSION-SIG': signature})
            response = connection.getresponse(); body = response.read(); connection.close()
            return response.status, body
        self.assertEqual(send('forged')[0], 403)
        self.assertIsNone(api.record_store().get_named('payments', checkout['purchase_id']))
        self.assertEqual(send('test-valid')[0], 200)
        self.assertEqual(send('test-valid')[0], 200)
        self.assertEqual(len(self.email_calls), 1)
        self.assertEqual(len(api.record_store().list_named('payment_events')), 1)

    def test_recovery_is_generic_throttled_and_preserves_entitlements(self):
        checkout = self.paid()
        before = self.redeem(checkout, self.request_code)[2]
        missing, _ = self.json_call({'action': 'purchase_recover', 'email': 'unknown@example.com'})
        # Unknown email and known email must not reveal customer existence.
        with patch.object(payments.time, 'time', return_value=1900001000):
            known, _ = self.json_call({'action': 'purchase_recover', 'email': 'buyer@example.com'})
            self.json_call({'action': 'purchase_recover', 'email': 'buyer@example.com'})
        self.assertEqual(known, missing)
        self.assertEqual(len(self.email_calls), 2)
        self.assertIn(checkout['token'], self.email_calls[-1][0]['text'])
        self.assertEqual(self.redeem(checkout, self.request_code)[2], before)
        self.assertEqual(len(api.record_store().all()), 1)

    def test_owner_sales_and_export_keep_tokens_private_and_escape_csv(self):
        checkout = self.paid(customer='=formula', referral='@referrer', discount_code='TEST10')
        for action in ['sales', 'sales_export', 'sale_link', 'sale_resend']:
            self.json_call({'action': action}, 401)
        cookie, csrf = self.login()
        self.json_call({'action': 'sales'}, 403, cookie=cookie)
        result, _ = self.json_call({'action': 'sales'}, cookie=cookie, csrf=csrf)
        sale, = result['sales']
        self.assertEqual(sale['amount_cents'], 4500)
        self.assertEqual(sale['payer_email'], 'paypal-payer@example.com')
        self.assertEqual(sale['referral'], '@referrer')
        self.assertNotIn('token', json.dumps(sale))
        exported = self.call({'action': 'sales_export'}, cookie, csrf)
        row, = list(csv.DictReader(io.StringIO(exported[2].decode('utf-8-sig'))))
        self.assertEqual(row['customer'], "'=formula")
        self.assertEqual(row['referral'], "'@referrer")
        link, _ = self.json_call({'action': 'sale_link', 'purchase_id': checkout['purchase_id']}, cookie=cookie, csrf=csrf)
        self.assertIn('#purchase=' + checkout['token'], link['url'])

    def test_purchase_links_survive_owner_session_rotation(self):
        checkout = self.paid()
        with patch.dict(os.environ, {'PARALLAX_SESSION_SECRET': 'new-owner-session-secret-' + 'x' * 32}):
            result, _ = self.json_call({'action': 'purchase_status', 'token': checkout['token']})
            self.assertTrue(result['paid'])
            self.redeem(checkout, self.request_code)

    def test_email_failure_does_not_lose_paid_access_and_webhook_retries_delivery(self):
        with patch.object(payments, 'json_request', side_effect=payments.CheckoutError(502, 'Email unavailable')):
            checkout = self.paid()
        self.assertTrue(self.json_call({'action': 'purchase_status', 'token': checkout['token']})[0]['paid'])
        self.assertEqual(len(self.email_calls), 0)
        order_id = api.record_store().get_named('purchase_orders', checkout['purchase_id'])['order_id']
        event = {'id': 'WEBHOOK-EMAIL-RETRY', 'event_type': 'PAYMENT.CAPTURE.COMPLETED',
                 'resource': {'supplementary_data': {'related_ids': {'order_id': order_id}}}}
        api.checkout_service().webhook(event, {'paypal-transmission-sig': 'test-valid'})
        self.assertEqual(len(self.email_calls), 1)
        self.assertEqual(self.gateway.captures, 1)


class GatewayContractTests(unittest.TestCase):
    def gateway(self):
        return RealGateway({'mode': 'sandbox', 'origin': 'https://example.com',
            'PARALLAX_PAYPAL_CLIENT_ID': 'test-client', 'PARALLAX_PAYPAL_CLIENT_SECRET': 'test-secret',
            'PARALLAX_PAYPAL_MERCHANT_ID': 'MERCHANT12345', 'PARALLAX_PAYPAL_WEBHOOK_ID': 'webhook-test'})

    def test_paypal_payload_keeps_server_price_discount_and_safe_return_url(self):
        gateway = self.gateway()
        purchase_id = payments.identifier('contract-test')
        purchase = {'purchase_id': purchase_id, 'price': {'total_cents': 4500, 'discount_cents': 500}}
        with patch.object(gateway, 'request', return_value={}) as request:
            gateway.create_order(purchase)
        method, endpoint, body, request_id = request.call_args.args
        self.assertEqual((method, endpoint), ('POST', '/v2/checkout/orders'))
        self.assertLessEqual(len(request_id), 38)
        self.assertEqual(body['purchase_units'][0]['amount']['value'], '45.00')
        self.assertEqual(body['purchase_units'][0]['amount']['breakdown']['discount']['value'], '5.00')
        self.assertEqual(body['purchase_units'][0]['custom_id'], purchase_id)
        experience = body['payment_source']['paypal']['experience_context']
        self.assertEqual(experience['shipping_preference'], 'NO_SHIPPING')
        self.assertEqual(experience['return_url'], 'https://example.com/parallax/activate/?checkout=' + purchase_id)
        self.assertNotIn('PLXP-', json.dumps(body))

    def test_real_webhook_verifier_requires_paypal_success_and_configured_webhook_id(self):
        gateway = self.gateway()
        headers = {name: 'test-value' for name in ['paypal-auth-algo', 'paypal-cert-url', 'paypal-transmission-id',
                                                 'paypal-transmission-sig', 'paypal-transmission-time']}
        with patch.object(gateway, 'request', return_value={'verification_status': 'FAILURE'}):
            with self.assertRaises(payments.CheckoutError): gateway.verify_webhook({'id': 'event'}, headers)
        with patch.object(gateway, 'request', return_value={'verification_status': 'SUCCESS'}) as request:
            gateway.verify_webhook({'id': 'event'}, headers)
            self.assertEqual(request.call_args.args[2]['webhook_id'], 'webhook-test')
        with self.assertRaises(payments.CheckoutError): gateway.verify_webhook({}, {})


if __name__ == '__main__':
    unittest.main()
