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
    from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False


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
    """Send email via Gmail SMTP or SendGrid (fallback). Returns (success, error_msg)."""
    
    # Try SendGrid first if configured and available
    if settings.SENDGRID_API_KEY and SENDGRID_AVAILABLE:
        success, error = _send_via_sendgrid(to_address, subject, body, attach_resume)
        if success:
            return True, ""
        # If SendGrid fails and Gmail is configured, try Gmail as fallback
        if settings.GMAIL_ADDRESS and settings.GMAIL_APP_PASSWORD:
            return _send_via_gmail(to_address, subject, body, attach_resume)
        return False, f"SendGrid failed: {error}"
    
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
    
    try:
        mail = Mail(
            from_email=settings.USER_EMAIL,
            to_emails=to_address,
            subject=subject,
            plain_text_content=body,
        )
        
        # Attach resume if requested
        if attach_resume:
            resume_path = Path(settings.RESUME_PATH)
            if resume_path.exists():
                with open(resume_path, "rb") as f:
                    file_content = f.read()
                filename = f"{settings.USER_FULL_NAME.replace(' ','_')}_Resume{resume_path.suffix}"
                attachment = Attachment(
                    FileContent(file_content),
                    FileName(filename),
                    FileType("application/octet-stream"),
                    Disposition("attachment"),
                )
                mail.attachment = attachment
        
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(mail)
        
        if 200 <= response.status_code < 300:
            return True, ""
        else:
            return False, f"SendGrid returned status {response.status_code}"
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
