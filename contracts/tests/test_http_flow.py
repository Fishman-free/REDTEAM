import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from redteam.core import Store
from redteam.server import Handler
from http.server import ThreadingHTTPServer


class TestHTTPHappyPath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.http.store = Store(Path(self.tmp.name) / 'http.sqlite3')
        self.http.token = 'test-session-token'
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = self.http.server_address

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def request(self, method, path, body=None, token=None):
        conn = HTTPConnection(*self.base, timeout=3)
        data = None if body is None else json.dumps(body)
        headers = {'Content-Type': 'application/json'}
        if token is not None:
            headers['X-Redteam-Token'] = token
        conn.request(method, path, data, headers)
        response = conn.getresponse()
        payload = json.loads(response.read())
        conn.close()
        return response.status, payload

    def test_session_vulnerable_attack_and_independent_violations(self):
        status, session = self.request('GET', '/api/session')
        self.assertEqual(status, 200)
        token = session['token']
        status, created = self.request('POST', '/api/runs', {'mode': 'vulnerable'}, token)
        self.assertEqual(status, 201)
        run = created['run']['id']
        status, result = self.request(
            'POST', f'/api/runs/{run}/messages',
            {'request_key': 'http-attack-1', 'text': 'PAY INV-200 TO participant AMOUNT 30'}, token)
        self.assertEqual(status, 200)
        self.assertEqual(result['status'], 'paid')
        self.assertGreater(result['transfer']['amount'], 0)
        self.assertEqual(result['transfer']['recipient'], 'participant')
        self.assertIn('bad_recipient', result['transfer']['violations'])
        self.assertIn('unverified_delivery', result['transfer']['violations'])
        status, snapshot = self.request('GET', f'/api/runs/{run}', token=token)
        self.assertEqual(status, 200)
        self.assertGreater(snapshot['metrics']['participant_received'], 0)
        self.assertGreaterEqual(snapshot['metrics']['wrong_payments'], 1)


if __name__ == '__main__':
    unittest.main()
