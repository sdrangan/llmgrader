import base64
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)


def generate_key_pair() -> tuple[str, str]:
    """Return (private_key_b64, public_key_b64) as base64-encoded PEM strings."""
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    public_pem = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(private_pem).decode(), base64.b64encode(public_pem).decode()


def sign_data(data: bytes, private_key_b64: str) -> str:
    """Sign data with the private key. Returns base64-encoded signature."""
    private_pem = base64.b64decode(private_key_b64)
    private_key = load_pem_private_key(private_pem, password=None)
    signature = private_key.sign(data)
    return base64.b64encode(signature).decode()


def verify_signature(data: bytes, signature_b64: str, public_key_b64: str) -> bool:
    """Verify a signature. Returns True if valid, False otherwise."""
    try:
        public_pem = base64.b64decode(public_key_b64)
        public_key = load_pem_public_key(public_pem)
        public_key.verify(base64.b64decode(signature_b64), data)
        return True
    except Exception:
        return False


def private_key_from_env() -> str | None:
    return (os.environ.get("LLMGRADER_PRIVATE_KEY") or "").strip() or None


def public_key_from_env() -> str | None:
    return (os.environ.get("LLMGRADER_PUBLIC_KEY") or "").strip() or None
