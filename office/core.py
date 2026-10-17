"""办公助手的核心逻辑(不依赖 MCP 库,方便单元测试)。

- 钉钉群自定义机器人 Webhook:加签、发送
- 「先草稿、后确认」的两步发送:避免语音听错或模型误调用时直接发出去
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

CONFIRM_TTL_SECONDS = 90


def sign(secret: str, timestamp_ms: int) -> str:
    """钉钉加签:HmacSHA256(key=secret, msg=f"{timestamp}\\n{secret}") -> Base64 -> urlEncode"""
    string_to_sign = f"{timestamp_ms}\n{secret}"
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    return urllib.parse.quote_plus(base64.b64encode(digest))


def build_webhook_url(webhook: str, secret: str | None, timestamp_ms: int | None = None) -> str:
    if not secret:
        return webhook
    ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
    sep = "&" if "?" in webhook else "?"
    return f"{webhook}{sep}timestamp={ts}&sign={sign(secret, ts)}"


@dataclass
class DingTalkConfig:
    webhook: str
    secret: str | None = None
    keyword: str | None = None  # 若机器人安全设置选了「自定义关键词」,消息里必须包含它

    @classmethod
    def from_env(cls) -> "DingTalkConfig":
        webhook = os.environ.get("DINGTALK_WEBHOOK", "").strip()
        if not webhook:
            raise RuntimeError("未配置 DINGTALK_WEBHOOK(见 office/.env.example)")
        return cls(
            webhook=webhook,
            secret=os.environ.get("DINGTALK_SECRET", "").strip() or None,
            keyword=os.environ.get("DINGTALK_KEYWORD", "").strip() or None,
        )


def post_json(url: str, payload: dict, timeout: float = 10.0) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_group_text(config: DingTalkConfig, text: str, poster=post_json) -> dict:
    """向钉钉群发一条文本消息。返回钉钉的原始响应;errcode==0 表示成功。"""
    if config.keyword and config.keyword not in text:
        text = f"{config.keyword} {text}"
    url = build_webhook_url(config.webhook, config.secret)
    return poster(url, {"msgtype": "text", "text": {"content": text}})


@dataclass
class PendingStore:
    """保存「已起草、待确认」的动作。确认码一次有效,超时作废。"""

    ttl: int = CONFIRM_TTL_SECONDS
    _items: dict = field(default_factory=dict)

    def add(self, kind: str, payload: dict, now: float | None = None) -> str:
        now = time.time() if now is None else now
        self._purge(now)
        code = f"{secrets.randbelow(10000):04d}"
        while code in self._items:
            code = f"{secrets.randbelow(10000):04d}"
        self._items[code] = (kind, payload, now + self.ttl)
        return code

    def pop(self, code: str, now: float | None = None):
        now = time.time() if now is None else now
        self._purge(now)
        item = self._items.pop(code, None)
        if item is None:
            return None
        return item[0], item[1]

    def _purge(self, now: float) -> None:
        for code in [c for c, (_, _, exp) in self._items.items() if exp < now]:
            del self._items[code]
