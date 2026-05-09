"""公网隧道启动与发现工具。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import shutil
import subprocess
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


logger = logging.getLogger(__name__)

DEFAULT_NGROK_API_URL = 'http://127.0.0.1:4040/api'


def local_tunnel_target(host: str, port: int) -> str:
    """将服务监听地址转换为隧道可访问的本机目标地址。"""
    local_host = (host or '').strip() or '127.0.0.1'
    if local_host in ('0.0.0.0', '::'):
        local_host = '127.0.0.1'
    if ':' in local_host and not local_host.startswith('['):
        local_host = f'[{local_host}]'
    return f'http://{local_host}:{port}'


def parse_ngrok_public_url(payload: dict[str, Any]) -> str | None:
    """从 ngrok agent API 响应中提取公网 URL，优先返回 HTTPS。"""
    records = payload.get('endpoints')
    if not isinstance(records, list):
        records = payload.get('tunnels')
    if not isinstance(records, list):
        return None

    public_urls = [
        public_url
        for record in records
        if isinstance(record, dict)
        for public_url in (record.get('url'), record.get('public_url'))
        if isinstance(public_url, str)
    ]
    for public_url in public_urls:
        if public_url.startswith('https://'):
            return public_url
    for public_url in public_urls:
        if public_url.startswith('http://'):
            return public_url
    return None


def ngrok_agent_urls(api_url: str) -> list[str]:
    """返回当前和旧版 ngrok agent API 的候选地址。"""
    normalized = api_url.rstrip('/')
    if normalized.endswith('/endpoints') or normalized.endswith('/tunnels'):
        return [normalized]
    return [f'{normalized}/endpoints', f'{normalized}/tunnels']


@dataclass
class NgrokTunnel:
    """管理一个 ngrok 子进程，并等待其公开 URL 可用。"""

    target_url: str
    command: str = 'ngrok'
    api_url: str = DEFAULT_NGROK_API_URL
    startup_timeout: float = 15.0

    process: subprocess.Popen[bytes] | None = None

    def start(self) -> str:
        """启动 ngrok 并返回公网 URL。"""
        if shutil.which(self.command) is None:
            raise RuntimeError(
                '未找到 ngrok 命令。请先安装 ngrok，并执行 '
                '`ngrok config add-authtoken <token>`。'
            )

        creationflags = 0
        if hasattr(subprocess, 'CREATE_NO_WINDOW'):
            creationflags = subprocess.CREATE_NO_WINDOW

        self.process = subprocess.Popen(
            [self.command, 'http', self.target_url],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
        try:
            return self.wait_for_public_url()
        except Exception:
            self.stop()
            raise

    def wait_for_public_url(self) -> str:
        """轮询 ngrok agent API，直到拿到公网 URL 或超时。"""
        deadline = time.monotonic() + self.startup_timeout
        last_error = 'ngrok 未返回公网 URL'
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                detail = self._process_output()
                message = 'ngrok 在创建隧道前已退出'
                if detail:
                    message = f'{message}: {detail}'
                raise RuntimeError(message)
            for api_url in ngrok_agent_urls(self.api_url):
                try:
                    with urlopen(api_url, timeout=1) as response:
                        payload = json.loads(response.read().decode('utf-8'))
                    public_url = parse_ngrok_public_url(payload)
                    if public_url:
                        return public_url
                except (OSError, URLError, json.JSONDecodeError) as exc:
                    last_error = str(exc)
            time.sleep(0.25)
        raise RuntimeError(
            f'等待 ngrok 隧道超时: {last_error}。'
            '请确认 ngrok 已登录并可访问公网。'
        )

    def stop(self) -> None:
        """停止 ngrok 子进程。"""
        if self.process is None or self.process.poll() is not None:
            return
        logger.info('正在停止 ngrok 隧道')
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    def _process_output(self) -> str:
        """读取已退出 ngrok 进程的输出，辅助定位未登录等问题。"""
        if self.process is None:
            return ''
        try:
            stdout, stderr = self.process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            return ''
        combined = b'\n'.join(part for part in (stdout, stderr) if part)
        return combined.decode('utf-8', errors='replace').strip()
