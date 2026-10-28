import copy
import json
import os
import tempfile
import unittest
import uuid
from unittest.mock import patch
from datetime import datetime
import main


class IntakeTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"DEV_MODE": "1", "LOCAL_DATA": self.directory.name,
            "ORDER_SECRET": "s" * 40, "ADMIN_TOKEN": "a" * 40}, clear=True)
        self.env.start()
        self.sent = []
        self.smtp = patch.object(main, 'send_mail', side_effect=lambda order: self.sent.append(copy.deepcopy(order)))
        self.smtp.start()

    def tearDown(self):
        self.smtp.stop()
        self.env.stop()
        self.directory.cleanup()

    def data(self, **extra):
        value = dict(requestId=uuid.uuid4().hex, product="birthday", recipient="测试收礼人",
                     desiredDate="2026-11-10", email="qa@example.com", details={"wish": "测试祝福", "secret": "测试许愿"},
                     materials="base", extras="", source="qa")
        value.update(extra)
        return value

    def call(self, path, body=None, method="POST", headers=None, ip="127.0.0.1"):
        event = {"rawPath": path, "requestContext": {"http": {"method": method, "sourceIp": ip}},
                 "headers": {"Content-Type": "application/json", **(headers or {})},
                 "body": json.dumps(body) if body is not None else ""}
        response = main.handler(json.dumps(event).encode(), None)
        return response["statusCode"], json.loads(response["body"]), response["headers"]

    def create(self, **extra):
        status, receipt, _ = self.call('/api/orders', self.data(**extra))
        self.assertEqual(status, 200)
        return receipt

    def claim(self, r, headers=None):
        return self.call('/api/orders/'+r['id']+'/payment-claim',
            {"paidDeclaration": True, "payerReference": "测试付款昵称 16:30"},
            headers=headers or {"X-Order-Token": r['accessToken']})

    def test_full_flow_and_admin_verification(self):
        r = self.create(amountMinor=1)
        self.assertEqual(r['amountMinor'], 990)
        self.assertEqual(r['paymentStatus'], 'unpaid')
        self.assertEqual(len(self.sent), 0)
        status, result, _ = self.claim(r)
        self.assertEqual(status, 200)
        self.assertEqual(result['paymentStatus'], 'claimed')
        self.assertEqual(result['notificationStatus'], 'sent')
        self.assertIn('待人工核验', main.summary(self.sent[0]))
        self.assertEqual(self.claim(r)[0], 200)
        self.assertEqual(len(self.sent), 1)
        headers = {'Authorization': 'Bearer '+'a'*40}
        result = self.call('/api/admin/orders/'+r['id']+'/verify', {}, headers=headers)
        self.assertEqual(result[1]['order']['paymentStatus'], 'verified')
        self.assertEqual(self.call('/api/admin/orders', method='GET', headers=headers)[1]['orders'][0]['id'], r['id'])

    def test_duplicate_request_and_changed_payload(self):
        data = self.data()
        first = self.call('/api/orders', data)[1]
        self.assertEqual(first, self.call('/api/orders', data)[1])
        data['recipient'] = '不同收礼人'
        self.assertEqual(self.call('/api/orders', data)[0], 409)
        self.assertEqual(len(main.FileStore().keys('orders/')), 1)

    def test_persistence_after_process_state_reset(self):
        r = self.create()
        self.assertEqual(main.FileStore().get('orders/'+r['id']+'.json')['email'], 'qa@example.com')

    def test_quote_never_prompts_fixed_payment(self):
        for extra in ({'materials': 'custom'}, {'materials': 'unsure'}, {'product': 'strawberry'}):
            r = self.create(**extra)
            self.assertTrue(r['quoteRequired'])
            self.assertIsNone(r['amountMinor'])
            self.assertEqual(self.claim(r)[0], 409)
        self.assertEqual(len(self.sent), 3)

    def test_smtp_failure_retry(self):
        r = self.create()
        with patch.object(main, 'send_mail', side_effect=TimeoutError):
            status, result, _ = self.claim(r)
        self.assertEqual(status, 200)
        self.assertEqual(result['notificationStatus'], 'pending_retry')
        self.assertEqual(main.FileStore().get('orders/'+r['id']+'.json')['paymentStatus'], 'claimed')
        self.assertEqual(main.handler({'job': 'retry_notifications'}, None)['attempted'], 1)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(main.handler({'job': 'retry_notifications'}, None)['attempted'], 0)

    def test_retry_exhaustion_and_manual_retry(self):
        r = self.create()
        with patch.object(main, 'send_mail', side_effect=ConnectionError):
            self.claim(r)
            for _ in range(9):
                main.handler({'triggerName': 'timer', 'payload': '{"job":"retry_notifications"}'}, None)
        order = main.FileStore().get('orders/'+r['id']+'.json')
        self.assertEqual(order['notificationAttempts'], 8)
        self.assertEqual(order['notificationStatus'], 'needs_attention')
        result = self.call('/api/admin/orders/'+r['id']+'/notify', {}, headers={'Authorization': 'Bearer '+'a'*40})
        self.assertEqual(result[1]['order']['notificationStatus'], 'sent')

    def test_admin_and_payment_authorization(self):
        r = self.create()
        self.assertEqual(self.call('/api/admin/orders', method='GET')[0], 401)
        self.assertEqual(self.claim(r, {'X-Order-Token': 'wrong'})[0], 403)
        self.assertEqual(self.call('/api/orders/'+r['id']+'/payment-claim', {'paidDeclaration': False}, headers={'X-Order-Token': r['accessToken']})[0], 400)
        self.assertNotIn('email', r)

    def test_input_validation_and_cors(self):
        for extra in ({'email': 'bad'}, {'email': 'a@b.com\r\nBcc:x@b.com'}, {'desiredDate': 'not-a-date'}, {'details': {}}, {'recipient': 'x'*31}, {'website': 'spam'}):
            self.assertEqual(self.call('/api/orders', self.data(**extra))[0], 400)
        self.assertEqual(self.call('/api/orders', self.data(), headers={'Origin':'https://evil.example'})[0], 403)
        status, _, headers = self.call('/api/orders', self.data(), headers={'Origin':'https://www.loveinzju.top'})
        self.assertEqual(status, 200)
        self.assertEqual(headers['Access-Control-Allow-Origin'], 'https://www.loveinzju.top')
        self.assertEqual(self.call('/api/orders', {'job': 'retry_notifications'})[0], 400)

    def test_fc_gateway_owns_production_cors_headers(self):
        with patch.dict(os.environ, {'DEV_MODE': '0'}):
            headers = main.response(200, {}, 'https://www.loveinzju.top')['headers']
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_rate_limit(self):
        for _ in range(12):
            self.create()
        self.assertEqual(self.call('/api/orders', self.data())[0], 429)

    def test_promotion_end_server_price(self):
        class After(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 11, 28, 0, 1, tzinfo=tz)
        with patch.object(main, 'datetime', After):
            r = self.create(product='record', details={'track':'测试曲目','message':'测试赠言'})
        self.assertEqual(r['amountMinor'], 1990)

    def test_smtp_recipient_fixed_and_reply_to(self):
        r = self.create()
        order = main.FileStore().get('orders/'+r['id']+'.json')
        # Exercise the actual email construction without any network send.
        self.smtp.stop()
        try:
            with patch.dict(os.environ, {'SMTP_USER':'loveshi1009@163.com','SMTP_PASSWORD':'TEST-NOT-A-SECRET'}), patch.object(main.smtplib, 'SMTP_SSL') as mock, patch.object(main.ssl, 'create_default_context'):
                main.send_mail(order)
                msg = mock.return_value.__enter__.return_value.send_message.call_args.args[0]
                self.assertEqual(msg['To'], 'loveshi1009@163.com')
                self.assertEqual(msg['Reply-To'], 'qa@example.com')
        finally:
            self.smtp.start()


if __name__ == '__main__':
    unittest.main(verbosity=2)
