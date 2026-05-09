import unittest

from utils.tunnel import (
    NgrokTunnel,
    local_tunnel_target,
    ngrok_agent_urls,
    parse_ngrok_public_url,
)


class TunnelTests(unittest.TestCase):
    def test_local_tunnel_target_uses_loopback_for_wildcard_hosts(self):
        self.assertEqual(local_tunnel_target('0.0.0.0', 3029), 'http://127.0.0.1:3029')
        self.assertEqual(local_tunnel_target('::', 3029), 'http://127.0.0.1:3029')

    def test_local_tunnel_target_formats_ipv6_hosts(self):
        self.assertEqual(local_tunnel_target('::1', 3029), 'http://[::1]:3029')

    def test_parse_ngrok_public_url_prefers_https(self):
        payload = {
            'tunnels': [
                {'public_url': 'http://example.ngrok-free.app'},
                {'public_url': 'https://example.ngrok-free.app'},
            ],
        }

        self.assertEqual(parse_ngrok_public_url(payload), 'https://example.ngrok-free.app')

    def test_parse_ngrok_public_url_supports_endpoint_api(self):
        payload = {'endpoints': [{'url': 'https://example.ngrok-free.app'}]}

        self.assertEqual(parse_ngrok_public_url(payload), 'https://example.ngrok-free.app')

    def test_parse_ngrok_public_url_ignores_missing_tunnels(self):
        self.assertIsNone(parse_ngrok_public_url({'tunnels': []}))
        self.assertIsNone(parse_ngrok_public_url({}))

    def test_ngrok_agent_urls_use_current_api_then_legacy_fallback(self):
        self.assertEqual(
            ngrok_agent_urls('http://127.0.0.1:4040/api'),
            [
                'http://127.0.0.1:4040/api/endpoints',
                'http://127.0.0.1:4040/api/tunnels',
            ],
        )

    def test_stop_terminates_running_process(self):
        process = FakeProcess()
        tunnel = NgrokTunnel('http://127.0.0.1:3029')
        tunnel.process = process

        tunnel.stop()

        self.assertTrue(process.terminated)
        self.assertTrue(process.waited)


class FakeProcess:
    def __init__(self):
        self.terminated = False
        self.waited = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.waited = True
        return 0


if __name__ == '__main__':
    unittest.main()
