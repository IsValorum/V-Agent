"""A handler that answers a POST without reading its body must not break the next request on the connection
(it used to be parsed from the leftover "{}" and fail with 501 "Unsupported method")."""
import http.client
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
sys.path.insert(0, str(ROOT))

import agent


class Quiet(agent.Handler):
    def do_POST(self):                      # answers without reading the body, like /api/harness/admin/stop did
        self.send_response(200)
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'ok')

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Length', '3')
        self.end_headers()
        self.wfile.write(b'get')


class UnreadBodyTests(unittest.TestCase):
    def test_next_request_on_the_same_connection_works(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Quiet)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            connection = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=10)
            for _ in range(3):
                connection.request('POST', '/x', body=b'{"a": 1}', headers={'Content-Type': 'application/json'})
                response = connection.getresponse()
                self.assertEqual((response.status, response.read()), (200, b'ok'))
                connection.request('GET', '/y')
                response = connection.getresponse()
                self.assertEqual((response.status, response.read()), (200, b'get'))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
