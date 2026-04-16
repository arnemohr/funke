"""Generate a VAPID key pair for Web Push.

Outputs base64url-encoded P-256 keys in the exact format the Web Push API
expects (65-byte uncompressed public point, 32-byte raw private scalar).

Usage:
    uv run python backend/scripts/generate_vapid_keys.py

Set the output as env vars:
    export VAPID_PUBLIC_KEY=...    # 87 chars, base64url
    export VAPID_PRIVATE_KEY=...   # 43 chars, base64url
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def main() -> None:
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key()

    # Public key as raw uncompressed point: 0x04 || X(32) || Y(32) = 65 bytes
    public_bytes = public.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    assert len(public_bytes) == 65, f"unexpected public key length: {len(public_bytes)}"
    assert public_bytes[0] == 0x04, "public key must start with 0x04"

    # Private key as raw 32-byte scalar
    private_numbers = private.private_numbers()
    private_bytes = private_numbers.private_value.to_bytes(32, "big")

    print(f"VAPID_PUBLIC_KEY={_b64url(public_bytes)}")
    print(f"VAPID_PRIVATE_KEY={_b64url(private_bytes)}")


if __name__ == "__main__":
    main()
