"""Email delivery behind an interface.

The outbox worker depends on `EmailSender`, not on SMTP, so tests can assert
what would have been sent without a mail server and a future provider swap does
not reach into the drain logic.

Message bodies carry single-use tokens. Nothing here logs a rendered body or a
payload — see SECURITY.md §10.
"""

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Protocol

from app.core.config import Settings

# Minimal templates. Real HTML rendering belongs with the frontend's URLs and is
# deliberately not invented here.
_TEMPLATES: dict[str, tuple[str, str]] = {
    "email_verification": (
        "Verify your email address",
        "Use this code to verify your Nexora AI account:\n\n{token}\n",
    ),
    "password_reset": (
        "Reset your password",
        "Use this code to reset your Nexora AI password:\n\n{token}\n"
        "If you did not request this, you can ignore this message.\n",
    ),
    "invitation": (
        "You have been invited to Nexora AI",
        "Use this code to accept your invitation:\n\n{token}\n",
    ),
}


@dataclass(frozen=True, slots=True)
class Message:
    to: str
    subject: str
    body: str


def render(payload: dict[str, Any]) -> Message:
    template = str(payload.get("template", ""))
    if template not in _TEMPLATES:
        raise ValueError(f"Unknown email template: {template!r}")
    subject, body = _TEMPLATES[template]
    return Message(
        to=str(payload["to"]),
        subject=subject,
        body=body.format(token=payload.get("token", "")),
    )


class EmailSender(Protocol):
    def send(self, message: Message) -> None: ...


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, message: Message) -> None:
        email = EmailMessage()
        email["From"] = f"{self.settings.email_from_name} <{self.settings.email_from}>"
        email["To"] = message.to
        email["Subject"] = message.subject
        email.set_content(message.body)
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as client:
            if self.settings.smtp_tls:
                client.starttls()
            if self.settings.smtp_user and self.settings.smtp_password:
                client.login(
                    self.settings.smtp_user, self.settings.smtp_password.get_secret_value()
                )
            client.send_message(email)


class CollectingEmailSender:
    """Records messages instead of sending. For tests and local runs."""

    def __init__(self) -> None:
        self.sent: list[Message] = []

    def send(self, message: Message) -> None:
        self.sent.append(message)
