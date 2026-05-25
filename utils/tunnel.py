"""公网隧道启动与发现工具。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import shutil
import shlex
import subprocess
import threading
import time
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen


logger = logging.getLogger(__name__)

DEFAULT_NGROK_API_URL = 'http://127.0.0.1:4040/api'
DEFAULT_CPOLAR_API_URL = 'http://127.0.0.1:4040/api'
_PUBLIC_URL_RE = re.compile(r'https?://[^\s\'"<>]+')


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
    return parse_agent_public_url(payload)


def parse_agent_public_url(payload: dict[str, Any]) -> str | None:
    """从常见隧道 agent API 响应中提取公网 URL，优先返回 HTTPS。"""
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
        if isinstance(public_url, str) and is_public_url_candidate(public_url)
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
    return tunnel_agent_urls(api_url)


def tunnel_agent_urls(api_url: str) -> list[str]:
    """返回常见隧道本地 agent API 的候选地址。"""
    normalized = api_url.rstrip('/')
    if normalized.endswith('/endpoints') or normalized.endswith('/tunnels'):
        return [normalized]
    return [f'{normalized}/endpoints', f'{normalized}/tunnels']


@dataclass
class ProcessTunnel:
    """管理一个隧道子进程，并等待其公开 URL 可用。"""

    name: str
    args: list[str]
    target_url: str
    startup_timeout: float = 15.0
    api_urls: list[str] | None = None
    public_url: str = ''
    url_pattern: str = ''

    process: subprocess.Popen[str] | None = None
    _output_lines: list[str] | None = None
    _output_lock: threading.Lock | None = None

    def start(self) -> str:
        """启动隧道命令并返回公网 URL。"""
        command = self.args[0]
        if shutil.which(command) is None:
            raise RuntimeError(
                f'未找到 {self.name} 命令 `{command}`。'
                f'请先安装 {self.name}，或在 .env 中配置正确的命令路径。'
            )

        creationflags = 0
        if hasattr(subprocess, 'CREATE_NO_WINDOW'):
            creationflags = subprocess.CREATE_NO_WINDOW

        self._output_lines = []
        self._output_lock = threading.Lock()
        self.process = subprocess.Popen(
            self.args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
        )
        self._start_output_readers()
        try:
            return self.wait_for_public_url()
        except Exception:
            self.stop()
            raise

    def wait_for_public_url(self) -> str:
        """轮询 agent API 和进程输出，直到拿到公网 URL 或超时。"""
        deadline = time.monotonic() + self.startup_timeout
        last_error = f'{self.name} 未返回公网 URL'
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                detail = self._process_output()
                message = f'{self.name} 在创建隧道前已退出'
                if detail:
                    message = f'{message}: {detail}'
                raise RuntimeError(message)

            if self.public_url:
                return self.public_url.rstrip('/')

            public_url = self._public_url_from_output()
            if public_url:
                return public_url.rstrip('/')

            for api_url in self.api_urls or []:
                try:
                    with urlopen(api_url, timeout=1) as response:
                        payload = json.loads(response.read().decode('utf-8'))
                    public_url = parse_agent_public_url(payload)
                    if public_url:
                        return public_url.rstrip('/')
                except (OSError, URLError, json.JSONDecodeError) as exc:
                    last_error = str(exc)
            time.sleep(0.25)
        raise RuntimeError(
            f'等待 {self.name} 隧道超时: {last_error}。'
            f'请确认 {self.name} 已登录、隧道配置有效并可访问公网。'
        )

    def stop(self) -> None:
        """停止隧道子进程。"""
        if self.process is None or self.process.poll() is not None:
            return
        logger.info('正在停止 %s 隧道', self.name)
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    def _process_output(self) -> str:
        """读取进程输出，辅助定位未登录、token 无效等问题。"""
        if not self._output_lines or self._output_lock is None:
            return ''
        with self._output_lock:
            return ''.join(self._output_lines[-40:]).strip()

    def _start_output_readers(self) -> None:
        """后台读取 stdout/stderr，避免子进程因管道塞满而卡住。"""
        if self.process is None:
            return
        for stream in (self.process.stdout, self.process.stderr):
            if stream is None:
                continue
            thread = threading.Thread(target=self._read_stream, args=(stream,), daemon=True)
            thread.start()

    def _read_stream(self, stream) -> None:
        for line in iter(stream.readline, ''):
            if self._output_lock is None or self._output_lines is None:
                continue
            with self._output_lock:
                self._output_lines.append(line)
                del self._output_lines[:-200]
        try:
            stream.close()
        except OSError:
            pass

    def _public_url_from_output(self) -> str | None:
        if not self._output_lines or self._output_lock is None:
            return None
        with self._output_lock:
            text = ''.join(self._output_lines)
        return parse_public_url_from_text(text, self.url_pattern)


@dataclass
class NgrokTunnel(ProcessTunnel):
    """管理一个 ngrok 子进程，并等待其公开 URL 可用。"""

    def __init__(
        self,
        target_url: str,
        command: str = 'ngrok',
        api_url: str = DEFAULT_NGROK_API_URL,
        startup_timeout: float = 15.0,
    ):
        super().__init__(
            name='ngrok',
            args=[command, 'http', target_url],
            target_url=target_url,
            startup_timeout=startup_timeout,
            api_urls=tunnel_agent_urls(api_url),
        )


class CpolarTunnel(ProcessTunnel):
    """管理一个 cpolar 子进程，并等待其公开 URL 可用。"""

    def __init__(
        self,
        port: int,
        target_url: str,
        command: str = 'cpolar',
        region: str = '',
        api_url: str = DEFAULT_CPOLAR_API_URL,
        startup_timeout: float = 15.0,
    ):
        args = [command, 'http']
        if region:
            args.append(f'-region={region}')
        args.append(str(port))
        super().__init__(
            name='cpolar',
            args=args,
            target_url=target_url,
            startup_timeout=startup_timeout,
            api_urls=tunnel_agent_urls(api_url),
        )


class NatappTunnel(ProcessTunnel):
    """管理一个 NATAPP 子进程，并等待其公开 URL 可用。"""

    def __init__(
        self,
        target_url: str,
        command: str = 'natapp',
        authtoken: str = '',
        config_path: str = '',
        public_url: str = '',
        startup_timeout: float = 15.0,
    ):
        args = [command]
        if config_path:
            args.append(f'-config={config_path}')
        elif authtoken:
            args.append(f'-authtoken={authtoken}')
        else:
            raise RuntimeError('TUNNEL_PROVIDER=natapp 时必须配置 NATAPP_AUTHTOKEN 或 NATAPP_CONFIG。')
        args.extend(['-log=stdout', '-loglevel=INFO'])
        super().__init__(
            name='natapp',
            args=args,
            target_url=target_url,
            startup_timeout=startup_timeout,
            public_url=public_url,
            url_pattern=r'https?://[^\s\'"<>]*natapp[^\s\'"<>]*',
        )


class CustomTunnel(ProcessTunnel):
    """管理用户自定义隧道命令。"""

    def __init__(
        self,
        command_template: str,
        host: str,
        port: int,
        target_url: str,
        public_url: str = '',
        url_pattern: str = '',
        startup_timeout: float = 15.0,
    ):
        if not command_template.strip():
            raise RuntimeError('TUNNEL_PROVIDER=custom 时必须配置 CUSTOM_TUNNEL_COMMAND。')
        command = command_template.format(host=host, port=port, target_url=target_url)
        args = shlex.split(command, posix=False if _is_windows_command(command) else True)
        if not args:
            raise RuntimeError('CUSTOM_TUNNEL_COMMAND 不能为空。')
        super().__init__(
            name='custom',
            args=args,
            target_url=target_url,
            startup_timeout=startup_timeout,
            public_url=public_url,
            url_pattern=url_pattern,
        )


def parse_public_url_from_text(text: str, url_pattern: str = '') -> str | None:
    """从命令输出中提取公网 URL，优先返回 HTTPS。"""
    if not text:
        return None
    pattern = re.compile(url_pattern) if url_pattern else _PUBLIC_URL_RE
    urls = [
        url
        for match in pattern.finditer(text)
        for url in (match.group(0).rstrip('.,;'),)
        if is_public_url_candidate(url)
    ]
    for url in urls:
        if url.startswith('https://'):
            return url
    for url in urls:
        if url.startswith('http://'):
            return url
    return None


def _is_windows_command(command: str) -> bool:
    return '\\' in command or '.exe' in command.lower()


def is_public_url_candidate(url: str) -> bool:
    """过滤掉本机调试页和常见内网地址，避免误当作公网入口。"""
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if not host:
        return False
    if host in ('localhost', '127.0.0.1', '0.0.0.0', '::1'):
        return False
    if host.startswith('127.') or host.startswith('10.') or host.startswith('192.168.'):
        return False
    if host.startswith('172.'):
        parts = host.split('.')
        if len(parts) >= 2:
            try:
                second = int(parts[1])
            except ValueError:
                return True
            if 16 <= second <= 31:
                return False
    return parsed.scheme in ('http', 'https')
