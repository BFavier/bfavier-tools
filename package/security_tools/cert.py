import os
import tempfile
import ipaddress
from typing import Type
from types import TracebackType
from datetime import datetime, UTC
from dataclasses import dataclass
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from datetime import datetime, UTC, timedelta


def generate_self_signed_cert(common_name: str = u"self-signed", key_size=2048, ip_addresses: list[str] = []) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    """
    generates a self-signed TLS certificate for the the provided IPv4 or IPv6 adresses,
    and the rsa private key used for signing the certificate
    """
    # Generate RSA private key
    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    # Build self-signed certificate
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(UTC)
    cert_builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=1))
    )
    # add the addresses for which the certificate is valid
    san_list: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1"))
    ] + [x509.IPAddress(ipaddress.ip_address(ip_address)) for ip_address in ip_addresses]
    cert_builder = cert_builder.add_extension(
        x509.SubjectAlternativeName(san_list),
        critical=False
    )
    # sign certificate
    cert = cert_builder.sign(key, hashes.SHA256())
    return cert, key


@dataclass
class CertKeyPair:
    """
    Describes a path to a self signed certificate and the corresponding private key
    """
    cert_path: str
    private_key_path: str


class SelfSignedCertificate:
    """
    Context manager for temporary TLS certificate and key files.
    Automatically deletes the files when exiting the context.

    Example
    -------
    >>> with SelfSignedCertificate(keys_size=4096) as cert_key:
    >>>     cert_path = cert_key.cert_path
    >>>     private_key_path = cdert_key.private_key_path

    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self) -> CertKeyPair:
        cert, key = generate_self_signed_cert(**self.kwargs)
        self.key_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
        self.cert_file = tempfile.NamedTemporaryFile(delete=False, suffix=".crt")
        self.key_file.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        self.key_file.close()
        self.cert_file.write(cert.public_bytes(serialization.Encoding.PEM))
        self.cert_file.close()
        return CertKeyPair(cert_path=self.cert_file.name, private_key_path=self.key_file.name)

    def __exit__(self, type_: Type[BaseException] | None, value: BaseException | None, traceback: TracebackType | None) -> bool | None:
        # Delete the temp files, ignore if already removed
        for f in [self.cert_file, self.key_file]:
            try:
                if f:
                    os.remove(f.name)
            except FileNotFoundError:
                pass
        # Do not suppress exceptions
        return False
