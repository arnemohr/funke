"""Tests for the SMTP MIME message construction, incl. inline images (T312)."""

from app.services.email_client import EmailMessage, InlineImage, SmtpClient


class TestInlineImages:
    """multipart/related wrapping for Content-ID referenced inline images."""

    def test_no_inline_images_no_related_wrapper(self):
        email = EmailMessage(
            to="a@example.com", subject="s", body_text="hi", body_html="<p>hi</p>",
        )
        mime = SmtpClient()._create_mime_message(email)

        assert mime.get_content_type() == "multipart/alternative"

    def test_inline_image_wraps_body_in_related(self):
        email = EmailMessage(
            to="a@example.com",
            subject="s",
            body_text="hi",
            body_html='<p>hi <img src="cid:qr-0"></p>',
            inline_images=[InlineImage(content_id="qr-0", content=b"\x89PNG\r\n\x1a\nfakepngdata")],
        )
        mime = SmtpClient()._create_mime_message(email)

        assert mime.get_content_type() == "multipart/related"
        parts = list(mime.walk())
        image_parts = [p for p in parts if p.get_content_maintype() == "image"]
        assert len(image_parts) == 1
        assert image_parts[0]["Content-ID"] == "<qr-0>"
        assert image_parts[0]["Content-Disposition"].startswith("inline")
        assert image_parts[0].get_payload(decode=True) == b"\x89PNG\r\n\x1a\nfakepngdata"

    def test_multiple_inline_images_each_get_own_content_id(self):
        email = EmailMessage(
            to="a@example.com",
            subject="s",
            body_text="hi",
            body_html='<p><img src="cid:qr-0"><img src="cid:qr-1"></p>',
            inline_images=[
                InlineImage(content_id="qr-0", content=b"image-zero"),
                InlineImage(content_id="qr-1", content=b"image-one"),
            ],
        )
        mime = SmtpClient()._create_mime_message(email)

        image_parts = [p for p in mime.walk() if p.get_content_maintype() == "image"]
        content_ids = {p["Content-ID"] for p in image_parts}
        assert content_ids == {"<qr-0>", "<qr-1>"}

    def test_inline_images_and_attachments_coexist(self):
        """An inline QR image plus a discrete file attachment nest correctly:
        mixed(related(alternative-body, image), attachment)."""
        from app.services.email_client import Attachment

        email = EmailMessage(
            to="a@example.com",
            subject="s",
            body_text="hi",
            body_html='<p><img src="cid:qr-0"></p>',
            inline_images=[InlineImage(content_id="qr-0", content=b"image-data")],
            attachments=[
                Attachment(
                    filename="bericht.pdf", content=b"%PDF-fake", content_type="application/pdf",
                ),
            ],
        )
        mime = SmtpClient()._create_mime_message(email)

        assert mime.get_content_type() == "multipart/mixed"
        parts = list(mime.walk())
        assert any(p.get_content_type() == "multipart/related" for p in parts)
        assert any(p.get_content_maintype() == "image" for p in parts)
        assert any(
            p.get_content_disposition() == "attachment" and p.get_filename() == "bericht.pdf"
            for p in parts
        )


class TestHeaderHygiene:
    """Deliverability header fixes: Date, aligned Message-ID, List-Unsubscribe."""

    def _settings(self, monkeypatch, sender="funke@mobilemachenschaften.de"):
        from app.services import email_client

        email_client.get_email_settings.cache_clear()
        monkeypatch.setattr(email_client, "get_email_settings", lambda: email_client.EmailSettings(
            smtp_sender_email=sender, smtp_sender_name="Verein",
        ))

    def test_date_header_present(self, monkeypatch):
        self._settings(monkeypatch)
        mime = SmtpClient()._create_mime_message(
            EmailMessage(to="a@example.com", subject="s", body_text="hi"),
        )
        assert mime["Date"] is not None
        # RFC 5322 date carries a weekday + GMT/UTC offset.
        assert "+0000" in mime["Date"] or "GMT" in mime["Date"]

    def test_message_id_domain_matches_sender(self, monkeypatch):
        self._settings(monkeypatch, sender="funke@mobilemachenschaften.de")
        mime = SmtpClient()._create_mime_message(
            EmailMessage(to="a@example.com", subject="s", body_text="hi"),
        )
        assert mime["Message-ID"].endswith("@mobilemachenschaften.de>")
        assert "funke.app" not in mime["Message-ID"]

    def test_message_id_falls_back_when_sender_has_no_at(self, monkeypatch):
        self._settings(monkeypatch, sender="")
        mime = SmtpClient()._create_mime_message(
            EmailMessage(to="a@example.com", subject="s", body_text="hi"),
        )
        # No crash; a syntactically valid Message-ID is still produced.
        assert mime["Message-ID"].startswith("<") and mime["Message-ID"].endswith(">")

    def test_list_unsubscribe_emitted_when_set(self, monkeypatch):
        self._settings(monkeypatch)
        mime = SmtpClient()._create_mime_message(
            EmailMessage(
                to="a@example.com", subject="s", body_text="hi",
                list_unsubscribe="<mailto:funke@mobilemachenschaften.de?subject=Abmelden>",
            ),
        )
        assert mime["List-Unsubscribe"] == "<mailto:funke@mobilemachenschaften.de?subject=Abmelden>"

    def test_list_unsubscribe_absent_when_unset(self, monkeypatch):
        self._settings(monkeypatch)
        mime = SmtpClient()._create_mime_message(
            EmailMessage(to="a@example.com", subject="s", body_text="hi"),
        )
        assert mime["List-Unsubscribe"] is None
