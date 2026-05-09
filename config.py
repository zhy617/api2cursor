"""环境变量配置"""

import os


_TRUE_VALUES = ('1', 'true', 'yes', 'on')
_FALSE_VALUES = ('0', 'false', 'no', 'off')


def _get_bool(name, default=False):
    """读取布尔环境变量，无法识别时回退到默认值。"""
    raw = os.getenv(name)
    if raw is None or raw == '':
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return default


def _get_float(name, default):
    """读取浮点环境变量，无法解析时回退到默认值。"""
    raw = os.getenv(name)
    if raw is None or raw == '':
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class Config:
    """集中声明服务运行依赖的环境变量配置。

    这个类不承担运行时逻辑，只作为模块级配置容器，统一暴露上游地址、
    鉴权密钥、端口、超时和调试开关，供应用启动、路由鉴权和请求转发层共享。
    """

    # 上游 API 地址
    PROXY_TARGET_URL = os.getenv('PROXY_TARGET_URL', 'https://api.anthropic.com')
    # 上游 API 密钥
    PROXY_API_KEY = os.getenv('PROXY_API_KEY', '')
    # 服务监听端口
    PROXY_PORT = int(os.getenv('PROXY_PORT', '3029'))
    # 请求超时时间（秒）
    API_TIMEOUT = int(os.getenv('API_TIMEOUT', '300'))
    # 访问鉴权密钥，留空则不启用鉴权
    ACCESS_API_KEY = os.getenv('ACCESS_API_KEY', '')

    # 公网隧道配置。默认启用，方便 Cursor 从公网访问本地代理。
    ENABLE_TUNNEL = _get_bool('ENABLE_TUNNEL', True)
    TUNNEL_PROVIDER = os.getenv('TUNNEL_PROVIDER', 'ngrok').strip().lower()
    NGROK_COMMAND = os.getenv('NGROK_COMMAND', 'ngrok')
    NGROK_API_URL = os.getenv('NGROK_API_URL', 'http://127.0.0.1:4040/api')
    TUNNEL_STARTUP_TIMEOUT = _get_float('TUNNEL_STARTUP_TIMEOUT', 15.0)

    # 调试模式分级：
    # - off: 关闭调试
    # - simple: 仅控制台调试日志
    # - verbose: 控制台调试 + 详细文件日志
    _debug_mode_raw = os.getenv('DEBUG_MODE', '').strip().lower()
    _legacy_debug = os.getenv('DEBUG', '').lower() in ('1', 'true', 'yes', 'on')
    if _debug_mode_raw in ('off', 'simple', 'verbose'):
        DEBUG_MODE = _debug_mode_raw
    else:
        DEBUG_MODE = 'simple' if _legacy_debug else 'off'

    DEBUG = DEBUG_MODE in ('simple', 'verbose')
    VERBOSE_FILE_LOG = DEBUG_MODE == 'verbose'
