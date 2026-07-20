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
