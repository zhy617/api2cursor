"""启动入口

用法: python start.py
"""

import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
)

from config import Config
from app import create_app
import settings


_HOST = '0.0.0.0'

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def main():
    """加载应用并以 Waitress 方式启动代理服务。"""
    app = create_app()
    tunnel = None

    try:
        tunnel, public_url = _start_tunnel_if_enabled()
        if public_url:
            public_url = public_url.rstrip('/')
            print(f'Cursor Base URL: {public_url}')
            print(f'公网管理面板: {public_url}/admin')

        print(f'代理服务启动于 {_HOST}:{Config.PROXY_PORT}')
        print(f'本地管理面板: http://localhost:{Config.PROXY_PORT}/admin')
    except RuntimeError as exc:
        logging.getLogger(__name__).error(str(exc))
        return 2

    print(f'上游地址: {settings.get_url()}')

    from waitress import serve
    try:
        serve(
            app,
            host=_HOST,
            port=Config.PROXY_PORT,
            channel_timeout=Config.API_TIMEOUT,
            send_bytes=1,
        )
    finally:
        if tunnel is not None:
            tunnel.stop()

    return 0


def _start_tunnel_if_enabled():
    """按配置启动公网隧道，并返回公网 URL。"""
    if not Config.ENABLE_TUNNEL:
        return None, None
    if not Config.ACCESS_API_KEY:
        raise RuntimeError(
            'ENABLE_TUNNEL=true 时必须配置 ACCESS_API_KEY，避免公开无鉴权代理。'
        )
    from utils.tunnel import (
        CpolarTunnel,
        CustomTunnel,
        NatappTunnel,
        NgrokTunnel,
        local_tunnel_target,
    )

    target_url = local_tunnel_target(_HOST, Config.PROXY_PORT)
    provider = Config.TUNNEL_PROVIDER
    print(f'正在启动 {provider} 隧道: {target_url}')

    if provider == 'ngrok':
        tunnel = NgrokTunnel(
            target_url=target_url,
            command=Config.NGROK_COMMAND,
            api_url=Config.NGROK_API_URL,
            startup_timeout=Config.TUNNEL_STARTUP_TIMEOUT,
        )
    elif provider == 'cpolar':
        tunnel = CpolarTunnel(
            port=Config.PROXY_PORT,
            target_url=target_url,
            command=Config.CPOLAR_COMMAND,
            region=Config.CPOLAR_REGION,
            api_url=Config.CPOLAR_API_URL,
            startup_timeout=Config.TUNNEL_STARTUP_TIMEOUT,
        )
    elif provider == 'natapp':
        tunnel = NatappTunnel(
            target_url=target_url,
            command=Config.NATAPP_COMMAND,
            authtoken=Config.NATAPP_AUTHTOKEN,
            config_path=Config.NATAPP_CONFIG,
            public_url=Config.NATAPP_PUBLIC_URL,
            startup_timeout=Config.TUNNEL_STARTUP_TIMEOUT,
        )
    elif provider == 'custom':
        tunnel = CustomTunnel(
            command_template=Config.CUSTOM_TUNNEL_COMMAND,
            host='127.0.0.1',
            port=Config.PROXY_PORT,
            target_url=target_url,
            public_url=Config.CUSTOM_TUNNEL_PUBLIC_URL,
            url_pattern=Config.CUSTOM_TUNNEL_URL_PATTERN,
            startup_timeout=Config.TUNNEL_STARTUP_TIMEOUT,
        )
    else:
        raise RuntimeError(
            f'不支持的 TUNNEL_PROVIDER: {provider}。'
            '可选值: ngrok / cpolar / natapp / custom'
        )
    return tunnel, tunnel.start()


if __name__ == '__main__':
    sys.exit(main())
