import base64
import json
import sys
import unittest

sys.path[:0] = ['agent', '.']
import app_updates
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def keypair():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return private, base64.b64encode(public).decode()


def manifest(version='1.2.0', **installer):
    body = {'product': 'V-Agent', 'version': version, 'installer': {
        'name': 'V-Agent_%s_x64-setup.exe' % version, 'size': 1234, 'sha256': 'a' * 64, **installer}}
    return json.dumps(body).encode()


class AppUpdateTests(unittest.TestCase):
    def test_signed_newer_release_is_accepted(self):
        private, public = keypair(); body = manifest()
        data = app_updates.validate_manifest(body, base64.b64encode(private.sign(body)).decode(), '1.0.0', public)
        self.assertTrue(data['newer'])

    def test_tampered_or_foreign_signature_is_rejected(self):
        private, public = keypair(); body = manifest()
        signature = base64.b64encode(private.sign(body)).decode()
        with self.assertRaises(ValueError):
            app_updates.validate_manifest(body.replace(b'aaaa', b'bbbb', 1), signature, '1.0.0', public)
        other, _ = keypair()
        with self.assertRaises(ValueError):
            app_updates.validate_manifest(body, base64.b64encode(other.sign(body)).decode(), '1.0.0', public)

    def test_older_or_same_version_is_not_offered(self):
        private, public = keypair()
        for version in ('1.0.0', '0.9.9'):
            body = manifest(version)
            data = app_updates.validate_manifest(body, base64.b64encode(private.sign(body)).decode(), '1.0.0', public)
            self.assertFalse(data['newer'])

    def test_downloads_outside_the_repository_are_refused(self):
        updater = app_updates.AppUpdates('owner/V-Agent')
        for url in ('https://evil.example/x.exe', 'https://github.com/someone/V-Agent/releases/download/v1/x.exe',
                    'http://github.com/owner/V-Agent/releases/download/v1/x.exe'):
            with self.assertRaises(ValueError):
                updater._get(url, 10)

    def test_minor_component_releases_are_not_app_updates(self):
        updater = app_updates.AppUpdates('owner/V-Agent')
        updater._get = lambda url, limit: json.dumps([{'tag_name': 'components-1.0.0-r2', 'assets': []}]).encode()
        state = updater.check()
        self.assertEqual(state['error'], ''); self.assertIsNone(state['available'])
        # An app release older than a components release is still the one examined.
        updater._get = lambda url, limit: json.dumps([{'tag_name': 'components-1.0.0-r3', 'assets': []},
                                                      {'tag_name': 'v1.1.0', 'assets': []}]).encode()
        self.assertIn('no signed update manifest', updater.check()['error'])

    def test_unpublished_or_private_repository_is_not_an_error(self):
        import urllib.error
        updater = app_updates.AppUpdates('owner/V-Agent')
        def missing(url, limit):
            raise urllib.error.HTTPError(url, 404, 'Not Found', {}, None)
        updater._get = missing
        state = updater.check()
        self.assertEqual(state['error'], ''); self.assertIsNone(state['available'])

    def test_unconfigured_repository_contacts_nothing(self):
        state = app_updates.AppUpdates('').check()
        self.assertFalse(state['configured']); self.assertIsNone(state['available'])


if __name__ == '__main__':
    unittest.main()
