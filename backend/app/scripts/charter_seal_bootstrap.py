"""One-off: issue the seal certificate for the Chartervertrag (spec 025).

Run once, after the KMS key exists:

    cd backend
    AWS_PROFILE=schaluppe uv run python -m app.scripts.charter_seal_bootstrap

It builds an X.509 certificate whose public key is the KMS key's, signs that
certificate **with the KMS key itself**, and writes the PEM to S3 where the API
reads it at cold start.

Why this is hand-assembled rather than four lines of `cryptography`:
`CertificateBuilder.sign()` needs a local private key, and the whole point of
the KMS key is that no such thing exists. So the TBSCertificate is built with
`asn1crypto`, its DER handed to `kms:Sign`, and the signature spliced into the
final structure.

Re-running is safe: it overwrites the certificate with a freshly dated one for
the same key. Existing sealed documents are unaffected — they carry their own
copy of the certificate that sealed them, and their RFC 3161 timestamp proves
the seal predates any expiry.
"""

import argparse
import datetime
import sys

import boto3
from asn1crypto import algos
from asn1crypto import keys as asn1keys
from asn1crypto import x509 as asn1x509

# EKU for document signing. This is the extension Let's Encrypt and ACM cannot
# issue — they produce `serverAuth` TLS certificates — and it is the reason a
# certificate has to be minted here rather than obtained.
EKU_DOCUMENT_SIGNING = "1.3.6.1.5.5.7.3.36"

CERT_S3_KEY = "contracts/_seal/cert.pem"
VALIDITY_YEARS = 10


def _pem(der: bytes) -> str:
    import base64
    import textwrap

    body = "\n".join(textwrap.wrap(base64.b64encode(der).decode(), 64))
    return f"-----BEGIN CERTIFICATE-----\n{body}\n-----END CERTIFICATE-----\n"


def build_certificate(kms_client, key_id: str, *, now: datetime.datetime) -> bytes:
    """Return DER bytes of a self-signed certificate over the KMS public key."""
    spki = asn1keys.PublicKeyInfo.load(kms_client.get_public_key(KeyId=key_id)["PublicKey"])

    name = asn1x509.Name.build({
        "country_name": "DE",
        "organization_name": "Verein fuer mobile Machenschaften e.V.",
        "common_name": "Funke Vertragssiegel",
    })
    algorithm = algos.SignedDigestAlgorithm({"algorithm": "sha256_rsa"})

    tbs = asn1x509.TbsCertificate({
        "version": "v3",
        # Serial from the clock: there is exactly one issuer and it issues one
        # certificate at a time, so uniqueness is all that is required.
        "serial_number": int(now.timestamp()),
        "signature": algorithm,
        "issuer": name,
        "validity": {
            "not_before": asn1x509.Time({"utc_time": now - datetime.timedelta(days=1)}),
            "not_after": asn1x509.Time(
                {"general_time": now + datetime.timedelta(days=365 * VALIDITY_YEARS)},
            ),
        },
        "subject": name,
        "subject_public_key_info": spki,
        "extensions": [
            {
                "extn_id": "key_usage",
                "critical": True,
                # non_repudiation is the bit that matters for a seal.
                "extn_value": asn1x509.KeyUsage({"digital_signature", "non_repudiation"}),
            },
            {
                "extn_id": "basic_constraints",
                "critical": True,
                "extn_value": asn1x509.BasicConstraints({"ca": False}),
            },
            {
                "extn_id": "extended_key_usage",
                "critical": False,
                "extn_value": asn1x509.ExtKeyUsageSyntax([EKU_DOCUMENT_SIGNING]),
            },
        ],
    })

    signature = kms_client.sign(
        KeyId=key_id,
        Message=tbs.dump(),
        MessageType="RAW",
        SigningAlgorithm="RSASSA_PKCS1_V1_5_SHA_256",
    )["Signature"]

    return asn1x509.Certificate({
        "tbs_certificate": tbs,
        "signature_algorithm": algorithm,
        "signature_value": signature,
    }).dump()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-name", default="dev")
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument(
        "--key-id",
        default=None,
        help="KMS key id or ARN. Defaults to the alias created by the CDK stack.",
    )
    parser.add_argument("--bucket", default=None, help="Defaults to funke-{env}-reports.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print the certificate without writing it to S3.",
    )
    args = parser.parse_args(argv)

    key_id = args.key_id or f"alias/funke-{args.env_name}-charter-seal"
    bucket = args.bucket or f"funke-{args.env_name}-reports"

    kms = boto3.client("kms", region_name=args.region)
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)

    try:
        der = build_certificate(kms, key_id, now=now)
    except kms.exceptions.NotFoundException:
        print(
            f"KMS key {key_id} not found. Deploy the CDK stack first:\n"
            f"  cd infra && AWS_PROFILE=… make deploy",
            file=sys.stderr,
        )
        return 1

    pem = _pem(der)

    # Read it back with the standard stack before trusting it anywhere.
    from cryptography.x509 import load_der_x509_certificate

    parsed = load_der_x509_certificate(der)
    print(f"subject   : {parsed.subject.rfc4514_string()}")
    print(
        f"valid     : {parsed.not_valid_before_utc.date()} "
        f"-> {parsed.not_valid_after_utc.date()}",
    )
    print(f"key id    : {key_id}")

    if args.dry_run:
        print("\n(dry run — not written)\n")
        print(pem)
        return 0

    boto3.client("s3", region_name=args.region).put_object(
        Bucket=bucket,
        Key=CERT_S3_KEY,
        Body=pem.encode(),
        ContentType="application/x-pem-file",
    )
    print(f"written   : s3://{bucket}/{CERT_S3_KEY}")
    print("\nDone. The API picks the certificate up on its next cold start.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
