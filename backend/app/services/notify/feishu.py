"""
Feishu (Lark) notification adapter.
Supports two modes:
  1. webhook_bot — custom bot webhook URL (simpler, recommended for start)
  2. feishu_app  — enterprise app with OAuth (supports more features)
"""
import json
import hashlib
import hmac
import base64
import time
from typing import Optional
import httpx
import structlog

from .base import NotificationProvider, NotifyMessage

logger = structlog.get_logger()

COLOR_MAP = {
    "blue": "blue",
    "green": "green",
    "red": "red",
    "yellow": "yellow",
}


def _build_code_review_card(data: dict, context: dict) -> dict:
    """Build Feishu interactive card for code review results."""
    findings = data.get("findings", [])
    score = data.get("score", 0)
    blocked = data.get("blocked", False)
    critical = sum(1 for f in findings if f.get("severity") == "critical")
    high = sum(1 for f in findings if f.get("severity") == "high")
    medium = sum(1 for f in findings if f.get("severity") == "medium")

    status_color = "red" if blocked else ("yellow" if high > 0 else "green")
    status_text = "❌ 拦截" if blocked else ("⚠️ 需关注" if high > 0 else "✅ 通过")

    findings_md = ""
    for f in findings[:5]:  # show top 5
        sev_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(f.get("severity", "low"), "⚪")
        findings_md += f"\n{sev_emoji} **{f.get('severity', '').upper()}** `{f.get('file', '')}:{f.get('line', '')}` — {f.get('message', '')}"

    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": f"🤖 AI 代码审核 {status_text}"},
                "template": status_color,
            },
            "body": {
                "direction": "vertical",
                "elements": [
                    {
                        "tag": "markdown",
                        "content": (
                            f"**仓库**: {context.get('repo', '')}\n"
                            f"**分支**: `{context.get('branch', '')}` | **提交**: `{context.get('commit', '')}`\n"
                            f"**作者**: {context.get('author', '')} | **MR**: {context.get('mr_title', 'N/A')}\n\n"
                            f"**审核评分**: {score}/100 | Critical: {critical} | High: {high} | Medium: {medium}"
                        ),
                    },
                    {"tag": "markdown", "content": f"**审核摘要**: {data.get('summary', '')}"},
                    *([{"tag": "markdown", "content": f"**主要问题**:{findings_md}"}] if findings_md else []),
                ],
            },
        },
    }


def _build_test_gen_card(data: dict, context: dict) -> dict:
    """Build card for test generation results."""
    files_count = len(data.get("files", []))
    framework = data.get("framework", "unknown")
    coverage = data.get("estimated_coverage_delta", "N/A")

    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": "🧪 AI 单测生成完成"},
                "template": "green",
            },
            "body": {
                "direction": "vertical",
                "elements": [
                    {
                        "tag": "markdown",
                        "content": (
                            f"**仓库**: {context.get('repo', '')}\n"
                            f"**分支**: `{context.get('branch', '')}` | **提交**: `{context.get('commit', '')}`\n\n"
                            f"**测试框架**: {framework}\n"
                            f"**生成文件数**: {files_count}\n"
                            f"**预估覆盖率提升**: {coverage}"
                        ),
                    }
                ],
            },
        },
    }


def _build_generic_card(message: NotifyMessage) -> dict:
    color = COLOR_MAP.get(message.color, "blue")
    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "header": {"title": {"tag": "plain_text", "content": message.title}, "template": color},
            "body": {
                "direction": "vertical",
                "elements": [{"tag": "markdown", "content": message.content}],
            },
        },
    }


class FeishuWebhookProvider(NotificationProvider):
    """Feishu custom bot via webhook URL."""

    def __init__(self, webhook_url: str, sign_key: Optional[str] = None):
        self.webhook_url = webhook_url
        self.sign_key = sign_key

    def get_provider_name(self) -> str:
        return "feishu_webhook"

    def _sign(self) -> dict:
        """Generate HMAC-SHA256 signature for webhook security."""
        if not self.sign_key:
            return {}
        timestamp = str(int(time.time()))
        content = f"{timestamp}\n{self.sign_key}"
        sign = base64.b64encode(
            hmac.new(content.encode("utf-8"), digestmod=hashlib.sha256).digest()
        ).decode("utf-8")
        return {"timestamp": timestamp, "sign": sign}

    def _build_payload(self, message: NotifyMessage) -> dict:
        base = self._sign()

        if message.message_type == "code_review_result" and message.data:
            card = _build_code_review_card(
                message.data.get("data", {}),
                message.data.get("context", {}),
            )
            return {**base, **card}
        elif message.message_type == "test_generation_result" and message.data:
            card = _build_test_gen_card(
                message.data.get("data", {}),
                message.data.get("context", {}),
            )
            return {**base, **card}

        return {**base, **_build_generic_card(message)}

    async def send(self, message: NotifyMessage) -> bool:
        payload = self._build_payload(message)
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(self.webhook_url, json=payload)
                resp.raise_for_status()
                result = resp.json()
                if result.get("code", 0) != 0:
                    logger.error("feishu.send_failed", code=result.get("code"), msg=result.get("msg"))
                    return False
                logger.info("feishu.sent", type=message.message_type)
                return True
            except Exception as e:
                logger.error("feishu.send_error", error=str(e))
                return False


def build_notify_provider(config: dict) -> NotificationProvider:
    """Factory: build provider from DB notify_config record."""
    provider_type = config.get("provider")
    cfg = config.get("config", {})

    if provider_type == "feishu_webhook":
        return FeishuWebhookProvider(
            webhook_url=cfg["webhook_url"],
            sign_key=cfg.get("sign_key"),
        )
    # TODO: feishu_app, slack (Phase 2 extension)
    raise ValueError(f"Unsupported notification provider: {provider_type}")
