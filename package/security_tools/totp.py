import hmac
import base64
import hashlib
from datetime import datetime, UTC


def totp_time_interval_index(at_time: datetime | None=None, period_seconds: int=30) -> int:
    """
    Returns the TOTP time interval index for easy offsetting.
    Time-Based One-Time Password Algorithm is an open standard: https://www.rfc-editor.org/rfc/rfc6238
    """
    if at_time is None:
        at_time = datetime.now(tz=UTC)
    assert at_time.tzinfo is not None
    at_time = at_time.replace(tzinfo=UTC) if at_time.tzinfo is None else at_time.astimezone(UTC)
    return int(at_time.timestamp()) // period_seconds


def totp_code(base32_secret: str, time_interval_index: int, n_digits: int=6) -> str:
    """
    Returns the TOTP code for the given time interval index and secret. Secret should be 15 bytes long for google MFA app.
    Time-Based One-Time Password Algorithm is an open standard: https://www.rfc-editor.org/rfc/rfc6238
    """
    base32_secret = base32_secret + "=" * ((8 - len(base32_secret) % 8) % 8)  # restore padding (characters count expected to be multiple of 8 because: 5 bits/char * 8 char = 40 bits = 5 bytes)
    secret = base64.b32decode(base32_secret.upper(), casefold=True)  # convert base32 secret
    time_bytes = time_interval_index.to_bytes(8, "big")  # Pack counter into 8 bytes (big-endian)
    hmac_hash = hmac.new(secret, time_bytes, hashlib.sha1).digest()  # HMAC-SHA1 of counter
    # Dynamic truncation
    offset = hmac_hash[-1] & 0x0F  # offset between 0 and 15
    chunk = hmac_hash[offset:offset + 4]
    binary = int.from_bytes(chunk, "big") & 0x7fffffff
    # Return zero-padded code
    return str(binary % (10 ** n_digits)).zfill(n_digits)


def totp_uri(issuer: str, user: str, base32_secret: str, n_digits: int=6, period_seconds: int=30):
    """
    URI to display as a QR code for MFA applications
    Time-Based One-Time Password Algorithm is an open standard: https://www.rfc-editor.org/rfc/rfc6238
    """
    assert ":" not in issuer
    assert ":" not in user
    return f"otpauth://totp/{issuer}:{user}?secret={base32_secret}&issuer={issuer}&digits={n_digits}&period={period_seconds}&algorithm=SHA1"

