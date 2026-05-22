"""
email_sender.py — Send emails via Gmail SMTP with resume attachment.

Gmail free limits:
  • 500 emails/day (personal account)
  • 2000 emails/day (Google Workspace)

Setup: Enable 2FA on Google account, then create an App Password at
       myaccount.google.com/apppasswords → "Mail" + "Windows Computer"
"""
from __future__ import annotations
import asyncio
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


GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 465   # SSL


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
    """Send a single email synchronously. Returns (success, error_msg)."""
    if not settings.GMAIL_ADDRESS or not settings.GMAIL_APP_PASSWORD:
        return False, "Gmail credentials not configured"
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
        # Return repr for clearer console logs and debugging
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
    print("[Email] Sending test email...")
    success = await send_email(
        to_address=settings.GMAIL_ADDRESS,
        subject="Job Auto-Apply — Configuration Test",
        body=(
            f"Hi {settings.USER_FULL_NAME},\n\n"
            "Your job auto-apply platform is configured correctly.\n\n"
            f"Gmail: {settings.GMAIL_ADDRESS}\n"
            f"Resume path: {settings.RESUME_PATH}\n\n"
            "You're all set!"
        ),
        attach_resume=False,
    )
    return success
