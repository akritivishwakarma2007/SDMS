import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

_RAW = dict(encoding=serialization.Encoding.Raw)


def generate_keypair() -> tuple[str, str]:
    """Returns (private_b64, public_b64)."""
    sk = Ed25519PrivateKey.generate()
    priv = sk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(priv).decode(), base64.b64encode(pub).decode()


def sign(priv_b64: str, message: bytes) -> str:
    sk = Ed25519PrivateKey.from_private_bytes(base64.b64decode(priv_b64))
    return base64.b64encode(sk.sign(message)).decode()


def verify(pub_b64: str, message: bytes, sig_b64: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64)).verify(base64.b64decode(sig_b64), message)
        return True
    except (InvalidSignature, ValueError):
        return False


def public_from_private(priv_b64: str) -> str:
    sk = Ed25519PrivateKey.from_private_bytes(base64.b64decode(priv_b64))
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(pub).decode()

