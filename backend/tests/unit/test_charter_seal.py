"""Tests for PAdES sealing of the Chartervertrag (spec 025).

The point of the seal is tamper-evidence, so the load-bearing test is the one
that flips a byte and expects the signature to break. Everything else is
plumbing around that.

KMS is mocked with moto. moto cannot itself issue the certificate that wraps
the KMS public key (that is a one-off, done in production with a real
``kms:Sign``), so a throwaway CA signs it here — irrelevant to what is being
tested, which is that pyHanko delegates the raw signature to KMS and that the
result detects modification.
"""

import datetime
import io

import boto3
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from moto import mock_aws

from app.services import charter_seal

NOW = datetime.datetime(2026, 8, 27, tzinfo=datetime.timezone.utc)

# A minimal but valid PDF is not enough — pyHanko needs a real document to do
# an incremental update on, so the renderer produces one.
pytest.importorskip("fpdf")


def _minimal_pdf() -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.cell(0, 10, "Chartervertrag")
    return bytes(pdf.output())


def _cert_for(public_key) -> str:
    ca = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Verein fuer mobile Machenschaften e.V."),
        x509.NameAttribute(NameOID.COMMON_NAME, "Funke Vertragssiegel"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - datetime.timedelta(days=1))
        .not_valid_after(NOW + datetime.timedelta(days=3650))
        .sign(ca, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


class TestSeal:
    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch, aws_credentials):
        with mock_aws():
            kms = boto3.client("kms", region_name="eu-central-1")
            key_id = kms.create_key(KeyUsage="SIGN_VERIFY", KeySpec="RSA_2048")
            key_id = key_id["KeyMetadata"]["KeyId"]
            pub = serialization.load_der_public_key(
                kms.get_public_key(KeyId=key_id)["PublicKey"],
            )

            monkeypatch.setenv("CHARTER_SEAL_KMS_KEY_ID", key_id)
            monkeypatch.setenv("CHARTER_SEAL_CERT_PEM", _cert_for(pub))
            # No network in tests: an empty TSA URL means B-B, not a hang.
            monkeypatch.setenv("CHARTER_SEAL_TSA_URL", "")
            charter_seal.get_seal_settings.cache_clear()
            charter_seal._cert_pem.cache_clear()
            self.key_id = key_id
            yield
            charter_seal.get_seal_settings.cache_clear()
            charter_seal._cert_pem.cache_clear()

    async def test_a_sealed_pdf_carries_a_signature(self):
        result = await charter_seal.seal_pdf(_minimal_pdf())

        from pyhanko.pdf_utils.reader import PdfFileReader

        sig = PdfFileReader(io.BytesIO(result.pdf)).embedded_signatures[0]
        assert sig.field_name == "VereinsSiegel"
        assert result.key_id == self.key_id

    async def test_sealing_grows_the_document_rather_than_replacing_it(self):
        original = _minimal_pdf()
        result = await charter_seal.seal_pdf(original)

        # An incremental update: the original bytes are still the prefix.
        assert len(result.pdf) > len(original)
        assert result.pdf.startswith(original[:1024])

    async def test_a_flipped_byte_breaks_the_seal(self):
        """The whole reason the seal exists.

        A modified file must not come back clean. It may fail either by
        validating as non-intact or by refusing to parse at all — both are
        detection, and which one you get depends on where the byte landed, so
        the assertion accepts either rather than pinning the failure mode.
        """
        from asn1crypto import x509 as asn1x509
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import async_validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext

        result = await charter_seal.seal_pdf(_minimal_pdf())

        # Self-signed: the seal certificate has to be its own trust root, or
        # validation fails for a reason that has nothing to do with tampering.
        settings = charter_seal.get_seal_settings()
        trust = asn1x509.Certificate.load(
            charter_seal._load_cert(settings.charter_seal_cert_pem).dump(),
        )
        vc = ValidationContext(
            trust_roots=[trust], allow_fetching=False, revocation_mode="soft-fail",
        )

        intact_sig = PdfFileReader(io.BytesIO(result.pdf)).embedded_signatures[0]
        assert (await async_validate_pdf_signature(intact_sig, vc)).intact is True

        async def still_intact(data: bytes) -> bool:
            try:
                sig = PdfFileReader(io.BytesIO(data)).embedded_signatures[0]
                return (await async_validate_pdf_signature(sig, vc)).intact
            except Exception:
                return False  # unparseable is detection too

        for offset in (len(result.pdf) // 3, len(result.pdf) // 2):
            tampered = bytearray(result.pdf)
            tampered[offset] ^= 0xFF
            assert not await still_intact(bytes(tampered)), (
                f"a flipped byte at {offset} went undetected"
            )

    async def test_an_unreachable_tsa_still_produces_a_seal(self, monkeypatch):
        """A missing timestamp must degrade to PAdES B-B, never block."""
        monkeypatch.setenv("CHARTER_SEAL_TSA_URL", "https://tsa.invalid/tsr")
        charter_seal.get_seal_settings.cache_clear()
        charter_seal._cert_pem.cache_clear()

        result = await charter_seal.seal_pdf(_minimal_pdf())

        assert result.timestamped is False
        assert len(result.pdf) > 0

    async def test_without_configuration_it_refuses_clearly(self, monkeypatch):
        monkeypatch.setenv("CHARTER_SEAL_KMS_KEY_ID", "")
        charter_seal.get_seal_settings.cache_clear()
        charter_seal._cert_pem.cache_clear()

        with pytest.raises(charter_seal.SealNotConfiguredError):
            await charter_seal.seal_pdf(_minimal_pdf())

    async def test_the_dry_run_placeholder_costs_no_kms_call(self):
        """pyHanko probes for signature size before signing; that probe must
        not be a billed, CloudTrail-logged KMS request."""
        signer = charter_seal.KMSSigner(
            self.key_id,
            charter_seal._load_cert(_cert_for(
                serialization.load_der_public_key(
                    boto3.client("kms", region_name="eu-central-1")
                    .get_public_key(KeyId=self.key_id)["PublicKey"],
                ),
            )),
            "eu-central-1",
        )
        calls = []
        signer._client = type("C", (), {"sign": lambda *a, **k: calls.append(1)})()

        out = await signer.async_sign_raw(b"x", "sha256", dry_run=True)

        assert out == b"\0" * 256
        assert calls == [], "a dry run must not call KMS"


class TestCertificateFromS3:
    """Production reads the certificate from S3; the env var is a dev fallback.

    Also exercises `charter_seal_bootstrap`, because a certificate the bootstrap
    writes and the seal module cannot read would be a very quiet failure.
    """

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch, aws_credentials):
        with mock_aws():
            kms = boto3.client("kms", region_name="eu-central-1")
            key_id = kms.create_key(KeyUsage="SIGN_VERIFY", KeySpec="RSA_2048")
            key_id = key_id["KeyMetadata"]["KeyId"]
            kms.create_alias(AliasName="alias/funke-test-charter-seal", TargetKeyId=key_id)
            boto3.client("s3", region_name="eu-central-1").create_bucket(
                Bucket="funke-test-reports",
                CreateBucketConfiguration={"LocationConstraint": "eu-central-1"},
            )
            monkeypatch.setenv("CHARTER_SEAL_KMS_KEY_ID", key_id)
            monkeypatch.setenv("CHARTER_SEAL_CERT_PEM", "")
            monkeypatch.setenv("CHARTER_SEAL_TSA_URL", "")
            monkeypatch.setenv("REPORTS_S3_BUCKET", "funke-test-reports")
            charter_seal.get_seal_settings.cache_clear()
            charter_seal._cert_pem.cache_clear()
            self.key_id = key_id
            yield
            charter_seal.get_seal_settings.cache_clear()
            charter_seal._cert_pem.cache_clear()

    async def test_a_bootstrapped_certificate_can_seal(self):
        from app.scripts.charter_seal_bootstrap import main

        assert main(["--env-name", "test"]) == 0
        charter_seal._cert_pem.cache_clear()

        result = await charter_seal.seal_pdf(_minimal_pdf())

        assert len(result.pdf) > 0
        assert result.key_id == self.key_id

    async def test_a_missing_certificate_disables_sealing_without_crashing(self):
        """No certificate in the bucket yet: refuse to seal, do not explode.

        This is the state between `cdk deploy` and running the bootstrap, and
        the whole feature has to stay usable through it.
        """
        with pytest.raises(charter_seal.SealNotConfiguredError):
            await charter_seal.seal_pdf(_minimal_pdf())

    def test_the_bootstrap_names_the_deploy_step_when_the_key_is_absent(self, capsys):
        from app.scripts.charter_seal_bootstrap import main

        rc = main(["--env-name", "nonexistent"])

        assert rc == 1
        assert "cdk" in capsys.readouterr().err.lower()

    async def test_a_certificate_that_appears_later_is_picked_up(self):
        """The operational trap: bootstrap runs *after* the Lambda is warm.

        A container that failed to find the certificate must retry, or running
        the bootstrap looks like it did nothing until the container recycles.
        """
        # First attempt with nothing in the bucket.
        with pytest.raises(charter_seal.SealNotConfiguredError):
            await charter_seal.seal_pdf(_minimal_pdf())

        # Now bootstrap, WITHOUT clearing any cache — the same process must
        # notice on its own.
        from app.scripts.charter_seal_bootstrap import main

        assert main(["--env-name", "test"]) == 0

        result = await charter_seal.seal_pdf(_minimal_pdf())
        assert len(result.pdf) > 0

    async def test_a_successful_read_is_not_repeated(self):
        """Success is still memoised — one S3 GET per container, not per seal."""
        from app.scripts.charter_seal_bootstrap import main

        assert main(["--env-name", "test"]) == 0
        assert charter_seal._cert_pem()

        calls = []
        original = charter_seal.boto3.client

        def counting(service, **kwargs):
            if service == "s3":
                calls.append(1)
            return original(service, **kwargs)

        charter_seal.boto3.client = counting
        try:
            charter_seal._cert_pem()
            charter_seal._cert_pem()
        finally:
            charter_seal.boto3.client = original

        assert calls == [], "a cached certificate must not hit S3 again"
