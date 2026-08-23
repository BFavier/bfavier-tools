import base64
import hashlib


def hash_password(password: str, salt: str) -> str:
    """
    hash a password with the given salt.
    This function is slightly costly to run to ensure that reversing password from salt and hash is prohibitively expensive
    """
    return base64.urlsafe_b64encode(
        hashlib.scrypt(
            password.encode(encoding="utf-8"),
            salt=salt.encode("utf-8"),
            n=2**14,
            r=8,
            p=1,
            dklen=64
        )
    ).rstrip(b'=').decode('utf-8')
