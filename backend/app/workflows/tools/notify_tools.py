"""Notification workflow tools — webhook and email."""

from __future__ import annotations

import httpx
import structlog

from app.workflows.tools.base import BaseTool, ToolInput, ToolOutput

logger = structlog.get_logger(__name__)


class NotifyWebhookTool(BaseTool):
    name = "notify.webhook"
    description = "Send an HTTP POST webhook notification."
    input_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "payload": {"type": "object"},
            "headers": {"type": "object"},
        },
        "required": ["url", "payload"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "status_code": {"type": "integer"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    params["url"],
                    json=params["payload"],
                    headers=params.get("headers", {}),
                )
            return ToolOutput(
                success=True,
                data={"status_code": response.status_code},
            )
        except Exception as e:
            logger.exception("webhook_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))


class NotifyEmailTool(BaseTool):
    name = "notify.email"
    description = "Send an email notification (via SMTP)."
    input_schema = {
        "type": "object",
        "properties": {
            "to": {"type": "array", "items": {"type": "string"}},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["to", "subject", "body"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "sent": {"type": "boolean"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        try:
            import smtplib
            from email.mime.text import MIMEText
            from app.config import get_settings

            settings = get_settings()
            smtp_host = getattr(settings, "smtp_host", None)

            if not smtp_host:
                logger.warning("email_skipped", reason="SMTP not configured")
                return ToolOutput(
                    success=True,
                    data={"sent": False, "reason": "SMTP not configured"},
                )

            msg = MIMEText(params["body"])
            msg["Subject"] = params["subject"]
            msg["To"] = ", ".join(params["to"])
            msg["From"] = getattr(settings, "smtp_from", "noreply@enterprise-rag.local")

            smtp_port = getattr(settings, "smtp_port", 587)
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                smtp_user = getattr(settings, "smtp_user", None)
                smtp_pass = getattr(settings, "smtp_password", None)
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.sendmail(msg["From"], params["to"], msg.as_string())

            return ToolOutput(success=True, data={"sent": True})
        except Exception as e:
            logger.exception("email_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))
