import resend

from app.config import get_settings


def send_email(
    recipient: str,
    subject: str,
    body: str,
) -> None:
    settings = get_settings()

    # Do nothing if Resend is not configured.
    if not settings.resend_api_key:
        return

    resend.api_key = settings.resend_api_key

    resend.Emails.send(
        {
            "from": settings.resend_from,
            "to": [recipient],
            "subject": subject,
            "text": body,
        }
    )