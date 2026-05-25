import unittest

from utils.tunnel import (
    CpolarTunnel,
    CustomTunnel,
    NatappTunnel,
    NgrokTunnel,
    local_tunnel_target,
    ngrok_agent_urls,
    parse_public_url_from_text,
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

    def test_parse_public_url_from_text_prefers_https(self):
        text = (
            'Web Interface http://127.0.0.1:4040\n'
            'Forwarding http://demo.cpolar.io -> localhost:3029\n'
            'Forwarding https://demo.cpolar.io -> localhost:3029'
        )

        self.assertEqual(parse_public_url_from_text(text), 'https://demo.cpolar.io')

    def test_parse_public_url_from_text_ignores_local_urls(self):
        self.assertIsNone(parse_public_url_from_text('Web Interface http://127.0.0.1:4040'))

    def test_parse_public_url_from_text_supports_custom_pattern(self):
        text = 'Tunnel online: https://demo.natappfree.cc'

        self.assertEqual(
            parse_public_url_from_text(text, r'https://[^\s]*natapp[^\s]*'),
            'https://demo.natappfree.cc',
        )

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

    def test_cpolar_builds_http_command_for_port(self):
        tunnel = CpolarTunnel(
            port=3029,
            target_url='http://127.0.0.1:3029',
            command='cpolar',
            region='cn_vip',
        )

        self.assertEqual(tunnel.args, ['cpolar', 'http', '-region=cn_vip', '3029'])

    def test_natapp_requires_token_or_config(self):
        with self.assertRaises(RuntimeError):
            NatappTunnel(target_url='http://127.0.0.1:3029')

    def test_custom_command_replaces_placeholders(self):
        tunnel = CustomTunnel(
            command_template='demo-tunnel --port {port} --target {target_url}',
            host='127.0.0.1',
            port=3029,
            target_url='http://127.0.0.1:3029',
        )

        self.assertEqual(
            tunnel.args,
            ['demo-tunnel', '--port', '3029', '--target', 'http://127.0.0.1:3029'],
        )


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
