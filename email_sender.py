"""
email_sender.py — Send emails via Gmail SMTP or SendGrid.

Gmail SMTP (free tier):
  • 500 emails/day (personal account)
  • 2000 emails/day (Google Workspace)
  • Setup: Enable 2FA, create App Password at myaccount.google.com/apppasswords

SendGrid (recommended for Render):
  • Free tier: 100 emails/day
  • Paid: ~$20/mo for unlimited
  • No SMTP restrictions on Render
  • Setup: Create account at sendgrid.com, get API key in Settings
  • Set SENDGRID_API_KEY in environment
"""
from __future__ import annotations
import asyncio
import base64
import mimetypes
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Optional
from datetime import datetime

from config import settings
from database import EmailLog, AsyncSessionLocal

try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import (
        Attachment,
        Bcc,
        Disposition,
        Email,
        FileContent,
        FileName,
        FileType,
        Mail,
        ReplyTo,
    )
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False


GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 465   # SSL


def _sendgrid_sender_email() -> str:
    """Return the verified sender address expected by SendGrid."""
    return (settings.USER_EMAIL or settings.GMAIL_ADDRESS or "").strip()


def _sender_name() -> str:
    return (settings.USER_FULL_NAME or "Mayur Koli").strip()


def _test_recipient_email() -> str:
    """Prefer the profile email, but allow Gmail-only local testing."""
    return (settings.USER_EMAIL or settings.GMAIL_ADDRESS or "").strip()


def _audit_bcc_email(to_address: str) -> str:
    audit_email = (settings.EMAIL_AUDIT_BCC or "").strip()
    if audit_email and audit_email.lower() != (to_address or "").lower():
        return audit_email
    return ""


def _configured_email_provider() -> str:
    if settings.SENDGRID_API_KEY and SENDGRID_AVAILABLE:
        return "SendGrid"
    if settings.SENDGRID_API_KEY and not SENDGRID_AVAILABLE:
        return "SendGrid configured, package unavailable"
    if settings.GMAIL_ADDRESS and settings.GMAIL_APP_PASSWORD:
        return "Gmail SMTP"
    return "not configured"


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    name, domain = email.split("@", 1)
    masked_name = f"{name[:2]}***{name[-1:]}" if len(name) > 2 else f"{name[:1]}*"
    return f"{masked_name}@{domain}"


def _sanitize_email_error(error: str) -> str:
    if not error:
        return ""
    lower = error.lower()
    if "401" in lower or "unauthorized" in lower:
        return "SendGrid rejected the API key. Check SENDGRID_API_KEY."
    if "403" in lower or "forbidden" in lower or "permission" in lower:
        return "SendGrid rejected the request. Check API key Mail Send permission and sender verification."
    if "verified sender" in lower or "sender identity" in lower or "from address" in lower:
        return "SendGrid sender is not verified. Verify USER_EMAIL as a Sender Identity."
    if "no email service configured" in lower:
        return "No email service configured. Set SENDGRID_API_KEY and USER_EMAIL, or Gmail fallback credentials."
    if "timed out" in lower or "timeout" in lower or "network is unreachable" in lower:
        return "Email provider connection timed out. SendGrid may be missing, causing Gmail SMTP fallback."
    return error[:500]


def _email_config_snapshot() -> dict:
    sender = _sendgrid_sender_email()
    recipient = _test_recipient_email()
    return {
        "sendgrid_key_present": bool(settings.SENDGRID_API_KEY),
        "sendgrid_package_available": SENDGRID_AVAILABLE,
        "gmail_config_present": bool(settings.GMAIL_ADDRESS and settings.GMAIL_APP_PASSWORD),
        "sender_present": bool(sender),
        "sender": _mask_email(sender),
        "recipient_present": bool(recipient),
        "recipient": _mask_email(recipient),
        "resume_attached": Path(settings.RESUME_PATH).exists(),
    }


def _email_failure_hint(provider: str, error: str) -> str:
    lower = (error or "").lower()
    if provider.startswith("SendGrid"):
        if "sender" in lower or "verified" in lower:
            return "In SendGrid, verify the exact USER_EMAIL address under Sender Authentication."
        if "api key" in lower:
            return "Regenerate a SendGrid API key with Mail Send access and set it as SENDGRID_API_KEY."
        return "Check Render environment variables, then redeploy or restart the service so the new key is loaded."
    if provider == "Gmail SMTP":
        return "SendGrid is not being used. Set SENDGRID_API_KEY on Render and redeploy or restart the service."
    return "Set SENDGRID_API_KEY and USER_EMAIL on Render, then redeploy or restart the service."


def _build_message(
    to_address: str,
    subject: str,
    body: str,
    from_name: str = None,
    cc: str = None,
    attach_resume: bool = True,
) -> MIMEMultipart:
    from_name = from_name or settings.USER_FULL_NAME
    msg = MIMEMultipart("mixed")
    msg["From"] = f"{from_name} <{settings.GMAIL_ADDRESS}>"
    msg["To"] = to_address
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc

    # Plain-text body
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # Resume attachment
    if attach_resume:
        resume_path = Path(settings.RESUME_PATH)
        if resume_path.exists():
            with open(resume_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            filename = f"{from_name.replace(' ','_')}_Resume{resume_path.suffix}"
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"'
            )
            msg.attach(part)

    return msg


def send_email_sync(
    to_address: str,
    subject: str,
    body: str,
    attach_resume: bool = True,
) -> tuple[bool, str]:
    """Send email via Gmail SMTP or SendGrid (fallback). Returns (success, error_msg)."""
    
    # Try SendGrid first if configured and available
    if settings.SENDGRID_API_KEY and SENDGRID_AVAILABLE:
        sendgrid_success, sendgrid_error = _send_via_sendgrid(to_address, subject, body, attach_resume)
        if sendgrid_success:
            return True, ""
        # If SendGrid fails and Gmail is configured, try Gmail as fallback
        if settings.GMAIL_ADDRESS and settings.GMAIL_APP_PASSWORD:
            gmail_success, gmail_error = _send_via_gmail(to_address, subject, body, attach_resume)
            if gmail_success:
                return True, ""
            return False, f"SendGrid failed: {sendgrid_error}; Gmail fallback failed: {gmail_error}"
        return False, f"SendGrid failed: {sendgrid_error}"
    if settings.SENDGRID_API_KEY and not SENDGRID_AVAILABLE:
        if settings.GMAIL_ADDRESS and settings.GMAIL_APP_PASSWORD:
            return _send_via_gmail(to_address, subject, body, attach_resume)
        return False, "SendGrid package not installed"
    
    # Fall back to Gmail
    if settings.GMAIL_ADDRESS and settings.GMAIL_APP_PASSWORD:
        return _send_via_gmail(to_address, subject, body, attach_resume)
    
    return False, "No email service configured (need SENDGRID_API_KEY or GMAIL_ADDRESS+GMAIL_APP_PASSWORD)"


def _send_via_gmail(
    to_address: str,
    subject: str,
    body: str,
    attach_resume: bool = True,
) -> tuple[bool, str]:
    """Send via Gmail SMTP."""
    try:
        msg = _build_message(to_address, subject, body, attach_resume=attach_resume)
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT, context=context, timeout=15) as server:
            server.login(settings.GMAIL_ADDRESS, settings.GMAIL_APP_PASSWORD)
            server.send_message(msg)
        return True, ""
    except smtplib.SMTPAuthenticationError as e:
        return False, f"Gmail auth failed — check App Password: {e}"
    except smtplib.SMTPRecipientsRefused as e:
        return False, f"Recipient refused: {to_address}: {e}"
    except Exception as e:
        return False, repr(e)


def _send_via_sendgrid(
    to_address: str,
    subject: str,
    body: str,
    attach_resume: bool = True,
) -> tuple[bool, str]:
    """Send via SendGrid API."""
    if not SENDGRID_AVAILABLE:
        return False, "SendGrid package not installed"
    sender_email = _sendgrid_sender_email()
    if not sender_email:
        return False, "USER_EMAIL or GMAIL_ADDRESS is required as the SendGrid sender"
    
    try:
        mail = Mail(
            from_email=Email(sender_email, _sender_name()),
            to_emails=to_address,
            subject=subject,
            plain_text_content=body,
        )
        mail.reply_to = ReplyTo(sender_email, _sender_name())
        audit_bcc = _audit_bcc_email(to_address)
        if audit_bcc and mail.personalizations:
            mail.personalizations[0].add_bcc(Bcc(audit_bcc))
        
        # Attach resume if requested
        if attach_resume:
            resume_path = Path(settings.RESUME_PATH)
            if resume_path.exists():
                with open(resume_path, "rb") as f:
                    file_content = f.read()
                filename = f"{settings.USER_FULL_NAME.replace(' ','_')}_Resume{resume_path.suffix}"
                encoded_content = base64.b64encode(file_content).decode("ascii")
                mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
                attachment = Attachment(
                    FileContent(encoded_content),
                    FileName(filename),
                    FileType(mime_type),
                    Disposition("attachment"),
                )
                mail.attachment = attachment
        
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(mail)
        
        if 200 <= response.status_code < 300:
            return True, ""
        else:
            body = getattr(response, "body", "") or ""
            return False, f"SendGrid returned status {response.status_code}: {body}"
    except Exception as e:
        return False, repr(e)


async def send_email(
    to_address: str,
    subject: str,
    body: str,
    job_id: str = None,
    to_name: str = "",
    attach_resume: bool = True,
) -> bool:
    """Async wrapper for send_email_sync; logs result to DB."""
    # Run SMTP in thread pool to not block event loop
    loop = asyncio.get_event_loop()
    success, error = await loop.run_in_executor(
        None,
        lambda: send_email_sync(to_address, subject, body, attach_resume)
    )

    # Log to DB
    async with AsyncSessionLocal() as session:
        log = EmailLog(
            job_id=job_id,
            to_address=to_address,
            to_name=to_name,
            subject=subject,
            body=body[:4000],   # trim for storage
            sent_at=datetime.utcnow(),
            success=success,
            error=error or None,
        )
        session.add(log)
        await session.commit()

    if success:
        print(f"[Email] ✓ Sent to {to_address} | Subject: {subject[:60]} | Job: {job_id or 'n/a'}")
    else:
        # Helpful troubleshooting hints
        hint = ""
        if error and 'auth' in error.lower():
            hint = " — check GMAIL_ADDRESS and GMAIL_APP_PASSWORD (no surrounding quotes)"
        print(f"[Email] ✗ Failed to {to_address} | Job: {job_id or 'n/a'}: {error}{hint}")

    return success


async def send_batch(
    emails: list[dict],
    delay_seconds: float = 60,
) -> int:
    """
    Send a batch of emails with a delay between each.
    emails: list of {"to": str, "subject": str, "body": str, "job_id": str, "to_name": str}
    delay_seconds: seconds to wait between sends (be Gmail-rate-limit friendly)
    Returns count of successful sends.
    """
    sent = 0
    for i, email_data in enumerate(emails):
        success = await send_email(
            to_address=email_data["to"],
            subject=email_data["subject"],
            body=email_data["body"],
            job_id=email_data.get("job_id"),
            to_name=email_data.get("to_name", ""),
        )
        if success:
            sent += 1
        # Rate limiting — don't send too fast
        if i < len(emails) - 1:
            await asyncio.sleep(delay_seconds)
    return sent


async def test_email_config() -> bool:
    """Send a test email to yourself to verify config."""
    result = await test_email_config_detailed()
    return bool(result["success"])


async def test_email_config_detailed() -> dict:
    """Send a test email and return sanitized diagnostics for API responses."""
    print("[Email] Sending test email...")
    recipient = _test_recipient_email()
    config = _email_config_snapshot()
    if not recipient:
        print("[Email] Test email skipped: set USER_EMAIL or GMAIL_ADDRESS first")
        return {
            "success": False,
            "message": "Email failed - check config",
            "provider": _configured_email_provider(),
            "config": config,
            "error": "USER_EMAIL or GMAIL_ADDRESS is required as the test recipient",
            "hint": "Set USER_EMAIL to the verified SendGrid sender address.",
        }

    provider = _configured_email_provider()
    subject = "Job Auto-Apply — Configuration Test"
    body = (
        f"Hi {settings.USER_FULL_NAME},\n\n"
        "Your job auto-apply platform is configured correctly.\n\n"
        f"Email provider: {provider}\n"
        f"Recipient: {recipient}\n"
        f"Resume path: {settings.RESUME_PATH}\n\n"
        "You're all set!"
    )

    loop = asyncio.get_event_loop()
    success, error = await loop.run_in_executor(
        None,
        lambda: send_email_sync(recipient, subject, body, False),
    )

    async with AsyncSessionLocal() as session:
        session.add(EmailLog(
            job_id=None,
            to_address=recipient,
            to_name=settings.USER_FULL_NAME,
            subject=subject,
            body=body[:4000],
            sent_at=datetime.utcnow(),
            success=success,
            error=error or None,
        ))
        await session.commit()

    if success:
        print(f"[Email] ✓ Test email sent to {recipient} via {provider}")
    else:
        print(f"[Email] ✗ Test email failed via {provider}: {error}")

    sanitized_error = _sanitize_email_error(error)
    return {
        "success": success,
        "message": "Check your inbox!" if success else "Email failed - check config",
        "provider": provider,
        "config": config,
        "error": sanitized_error or None,
        "hint": None if success else _email_failure_hint(provider, sanitized_error),
    }
