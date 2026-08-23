import os
import base64
from typing import Literal


def generate_secret(n_bytes: int=128, base: Literal[32, 64]=64, padded: bool=False) -> str:
    """
    generates an url safe random secret, to be used for salt, IDs, or tokens
    """
    random_secret = os.urandom(n_bytes)
    if base == 64:
        secret = base64.urlsafe_b64encode(random_secret).decode('utf-8')
    elif base == 32:
        secret = base64.b32encode(random_secret).decode("utf-8")
    if not padded:
        secret = secret.rstrip("=")
    return secret
