"""PAdES sealing of the finished Chartervertrag (spec 025).

Seals a rendered contract so that any later change to its bytes is detectable.
What this proves and what it does not, stated plainly because a legal spec
should not overclaim:

- It proves the document has **not been altered since it was sealed**.
- It does **not** prove who signed. That is what the per-signer audit record on
  the contract row is for (timestamp, IP, user agent, and the hash of the
  document the signer was actually shown).
- It does not stop somebody holding ``kms:Sign`` from sealing a doctored
  document. It does mean the key cannot be stolen and used elsewhere, and that
  every use is recorded in CloudTrail independently of this application.

The signing key is an **asymmetric AWS KMS key** (``SIGN_VERIFY``). It is
generated inside the HSM and is not exportable, so there is no key material in
this process, in the Lambda environment, or in the CloudFormation template.
That is the whole reason for KMS here: secrets otherwise reach this Lambda as
plaintext environment variables (see ``api_stack.py``), which is an acceptable
home for an SMTP password and not for a signing key.

The certificate wrapped around the KMS public key is self-signed and read from
config. A certificate is public, so an environment variable is fine. Swapping
in a CA-issued seal certificate later is a config change, not a code change.
"""

import asyncio
import io
from dataclasses import dataclass
from functools import lru_cache

import boto3
from asn1crypto import algos
from asn1crypto import x509 as asn1x509
from pydantic_settings import BaseSettings
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers
from pyhanko.sign.fields import SigSeedSubFilter
from pyhanko.sign.signers import Signer
from pyhanko.sign.timestamps import HTTPTimeStamper

from .logging import get_logger

logger = get_logger(__name__)

# KMS signing-algorithm identifiers, keyed by the digest pyHanko asks for.
# Only RSA PKCS#1 v1.5 is listed: it is what Acrobat and the PAdES baseline
# profiles expect, and PSS buys nothing here.
_KMS_ALGORITHMS = {
    "sha256": "RSASSA_PKCS1_V1_5_SHA_256",
    "sha384": "RSASSA_PKCS1_V1_5_SHA_384",
    "sha512": "RSASSA_PKCS1_V1_5_SHA_512",
}


class CharterSealSettings(BaseSettings):
    """Seal configuration. All three are optional — an unconfigured install
    renders and signs contracts perfectly well, it just cannot seal them."""

    charter_seal_kms_key_id: str = ""
    # The certificate lives in S3, not in an environment variable. It would
    # have fitted (the env block is ~1.1 KB of its 4 KB budget), but S3 means
    # one deploy instead of two — create key, mint certificate, done — and a
    # later certificate swap needs no deploy at all.
    reports_s3_bucket: str = ""
    charter_seal_cert_key: str = "contracts/_seal/cert.pem"
    # Escape hatch for local development and tests, where there is no bucket.
    charter_seal_cert_pem: str = ""
    # RFC 3161 timestamp authority. A third party attesting that the hash
    # existed at a point in time is worth more than the seal alone, because it
    # does not depend on trusting the Verein's own clock.
    charter_seal_tsa_url: str = "https://freetsa.org/tsr"
    aws_region: str = "eu-central-1"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_seal_settings() -> CharterSealSettings:
    return CharterSealSettings()


# Success is memoised for the life of the container; **failure is not**.
# `lru_cache` cannot express that — it stores the return value after the call,
# so a container that started before the certificate was bootstrapped would
# keep the empty string until it recycled, and running the bootstrap would look
# like it had done nothing. That is the whole reason this is a hand-rolled
# cache rather than a decorator.
_CERT_CACHE: str | None = None


def _cert_pem() -> str:
    """The seal certificate. Read from S3 once, on first successful use."""
    global _CERT_CACHE
    if _CERT_CACHE:
        return _CERT_CACHE

    settings = get_seal_settings()
    if settings.charter_seal_cert_pem:
        _CERT_CACHE = settings.charter_seal_cert_pem
        return _CERT_CACHE
    if not settings.reports_s3_bucket:
        return ""
    try:
        obj = boto3.client("s3", region_name=settings.aws_region).get_object(
            Bucket=settings.reports_s3_bucket,
            Key=settings.charter_seal_cert_key,
        )
        pem = obj["Body"].read().decode()
    except Exception as exc:  # noqa: BLE001 — an absent certificate is a config state
        logger.warning(
            "Seal certificate not readable; sealing stays disabled",
            extra={"key": settings.charter_seal_cert_key, "error": str(exc)[:120]},
        )
        return ""

    _CERT_CACHE = pem
    return pem


def _clear_cert_cache() -> None:
    global _CERT_CACHE
    _CERT_CACHE = None


# Keeps `_cert_pem.cache_clear()` working for callers and tests that grew up
# against the decorated version.
_cert_pem.cache_clear = _clear_cert_cache


class SealNotConfiguredError(RuntimeError):
    """No KMS key or no certificate. The caller answers 503 and keeps the
    signature — an unsealed signed contract is still a signed contract."""


@dataclass
class SealResult:
    pdf: bytes
    key_id: str
    timestamped: bool


class KMSSigner(Signer):
    """pyHanko signer that delegates the raw signature to AWS KMS.

    pyHanko builds the whole CMS structure and hands us just the bytes to sign;
    the private key never leaves the HSM.
    """

    def __init__(self, key_id: str, cert: asn1x509.Certificate, region: str):
        self._key_id = key_id
        self._cert = cert
        self._region = region
        # boto3 clients are not async; calls are pushed to a thread below.
        self._client = boto3.client("kms", region_name=region)
        super().__init__()

    @property
    def signing_cert(self) -> asn1x509.Certificate:
        return self._cert

    @property
    def cert_registry(self):
        return None

    def get_signature_mechanism_for_digest(self, digest_algorithm):
        algo = (digest_algorithm or "sha256").lower()
        return algos.SignedDigestAlgorithm({"algorithm": f"{algo}_rsa"})

    async def async_sign_raw(self, data: bytes, digest_algorithm: str, dry_run=False) -> bytes:
        algo = (digest_algorithm or "sha256").lower()
        try:
            kms_algo = _KMS_ALGORITHMS[algo]
        except KeyError:
            raise ValueError(f"Unsupported digest for KMS signing: {digest_algorithm}") from None

        if dry_run:
            # pyHanko only needs a correctly sized placeholder to reserve space.
            # Burning a real (billed, logged) KMS call for that would be silly.
            return b"\0" * 256

        def _sign() -> bytes:
            return self._client.sign(
                KeyId=self._key_id,
                Message=data,
                MessageType="RAW",
                SigningAlgorithm=kms_algo,
            )["Signature"]

        return await asyncio.to_thread(_sign)


def _load_cert(pem: str) -> asn1x509.Certificate:
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509 import load_pem_x509_certificate

    cert = load_pem_x509_certificate(pem.encode())
    return asn1x509.Certificate.load(cert.public_bytes(Encoding.DER))


async def seal_pdf(pdf: bytes, *, field_name: str = "VereinsSiegel") -> SealResult:
    """Seal `pdf` and return the sealed bytes.

    Raises:
        SealNotConfiguredError: no KMS key or certificate configured.
    """
    settings = get_seal_settings()
    pem = _cert_pem()
    if not settings.charter_seal_kms_key_id or not pem:
        raise SealNotConfiguredError(
            "Siegel nicht eingerichtet: CHARTER_SEAL_KMS_KEY_ID fehlt oder das "
            "Zertifikat liegt nicht in S3 (app/scripts/charter_seal_bootstrap.py).",
        )

    signer = KMSSigner(settings.charter_seal_kms_key_id, _load_cert(pem), settings.aws_region)

    # A missing timestamp must never block a signature. If the TSA is
    # unreachable we fall back from PAdES B-T to B-B and record which we got,
    # rather than refusing to seal at all.
    timestamper = None
    timestamped = False
    if settings.charter_seal_tsa_url:
        try:
            timestamper = HTTPTimeStamper(settings.charter_seal_tsa_url, timeout=8)
            await timestamper.async_dummy_response("sha256")
            timestamped = True
        except Exception as exc:  # noqa: BLE001 — any TSA failure is non-fatal
            logger.warning(
                "Timestamp authority unreachable, sealing without RFC 3161 timestamp",
                extra={"tsa": settings.charter_seal_tsa_url, "error": str(exc)[:120]},
            )
            timestamper = None

    writer = IncrementalPdfFileWriter(io.BytesIO(pdf))
    meta = signers.PdfSignatureMetadata(
        field_name=field_name,
        reason="Chartervertrag",
        location="Hamburg",
        subfilter=SigSeedSubFilter.PADES,
    )
    out = await signers.async_sign_pdf(writer, meta, signer=signer, timestamper=timestamper)

    return SealResult(
        pdf=out.getvalue(),
        key_id=settings.charter_seal_kms_key_id,
        timestamped=timestamped,
    )
