"""Interactive SMTP integration test.

Run with: python -m tests.integration.test_smtp_send
Prompts for credentials and recipient, then sends a test email.
"""

import asyncio
import getpass


async def main():
    print("=== Funke SMTP Test ===\n")

    host = input("SMTP Host [smtp.strato.de]: ").strip() or "smtp.strato.de"
    port = input("SMTP Port [465]: ").strip() or "465"
    use_ssl = input("Use SSL? [y/n, default y]: ").strip().lower() or "y"
    username = input("SMTP Username (email): ").strip()
    password = getpass.getpass("SMTP Password: ")
    sender_email = input(f"Sender email [{username}]: ").strip() or username
    sender_name = input("Sender name [Verein für mobile Machenschaften e.V.]: ").strip() or "Verein für mobile Machenschaften e.V."
    recipient = input("Recipient email: ").strip()

    if not all([username, password, recipient]):
        print("ERROR: Username, password, and recipient are required.")
        return

    # Set env vars before importing (pydantic-settings reads from env)
    import os

    os.environ["SMTP_HOST"] = host
    os.environ["SMTP_PORT"] = port
    os.environ["SMTP_USE_SSL"] = "true" if use_ssl == "y" else "false"
    os.environ["SMTP_USERNAME"] = username
    os.environ["SMTP_PASSWORD"] = password
    os.environ["SMTP_SENDER_EMAIL"] = sender_email
    os.environ["SMTP_SENDER_NAME"] = sender_name

    # Clear cached settings so our env vars are picked up
    from app.services.email_client import EmailMessage, SmtpClient, get_email_settings

    get_email_settings.cache_clear()

    client = SmtpClient()
    message = EmailMessage(
        to=recipient,
        subject="Funke Testmail",
        body_text="Moin! Dies ist eine Testnachricht vom Funke Event-System.",
        body_html="""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; line-height: 1.6; color: #333;">
    <h2>Funke Testmail</h2>
    <p>Moin!</p>
    <p>Dies ist eine Testnachricht vom Funke Event-System.</p>
    <p>Wenn du diese Mail lesen kannst, funktioniert der SMTP-Versand.</p>
    <p>Bis bald,<br>Dein Team vom Verein für mobile Machenschaften</p>
</body>
</html>
""",
    )

    print(f"\nSending test email to {recipient} via {host}:{port} ...")
    result = await client.send_email(message)

    if result.success:
        print(f"SUCCESS! Message-ID: {result.message_id}")
    else:
        print(f"FAILED: {result.error}")


if __name__ == "__main__":
    asyncio.run(main())
