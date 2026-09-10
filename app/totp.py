import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


TOTP_PERIOD = 30


def generate_secret():
    """Return a 160-bit Base32 secret accepted by authenticator apps."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def provisioning_uri(secret, account_name, issuer):
    label = quote(f"{issuer}:{account_name}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}"
        f"&issuer={quote(issuer, safe='')}&algorithm=SHA1&digits=6&period={TOTP_PERIOD}"
    )


def _counter(timestamp=None):
    return int(time.time() if timestamp is None else timestamp) // TOTP_PERIOD


def code_for_counter(secret, counter):
    padding = "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(secret.upper() + padding, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{number % 1_000_000:06d}"


def current_code(secret, timestamp=None):
    return code_for_counter(secret, _counter(timestamp))


def verify_code(secret, candidate, timestamp=None, valid_window=1):
    normalized = "".join((candidate or "").split())
    if len(normalized) != 6 or not normalized.isdigit():
        return None
    current_counter = _counter(timestamp)
    for offset in range(-valid_window, valid_window + 1):
        counter = current_counter + offset
        if hmac.compare_digest(code_for_counter(secret, counter), normalized):
            return counter
    return None
