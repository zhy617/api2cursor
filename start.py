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
    if Config.TUNNEL_PROVIDER != 'ngrok':
        raise RuntimeError(f'不支持的 TUNNEL_PROVIDER: {Config.TUNNEL_PROVIDER}')

    from utils.tunnel import NgrokTunnel, local_tunnel_target

    target_url = local_tunnel_target(_HOST, Config.PROXY_PORT)
    print(f'正在启动 ngrok 隧道: {target_url}')
    tunnel = NgrokTunnel(
        target_url=target_url,
        command=Config.NGROK_COMMAND,
        api_url=Config.NGROK_API_URL,
        startup_timeout=Config.TUNNEL_STARTUP_TIMEOUT,
    )
    return tunnel, tunnel.start()


if __name__ == '__main__':
    sys.exit(main())
