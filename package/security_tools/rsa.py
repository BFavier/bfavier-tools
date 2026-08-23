from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature


class RSAPrivateKey:
    """
    Represents a private RSA key
    """

    def __repr__(self):
        return f"{type(self).__name__}(size={self.size}, e={self.e}, d={self.d}, n={self.n})"

    def __init__(self, key: rsa.RSAPrivateKey):
        self.key = key

    @classmethod
    def generate(cls, public_exponent: int=65537, key_size: int=2048):
        return cls(rsa.generate_private_key(public_exponent=public_exponent, key_size=key_size))

    @classmethod
    def load(cls, data: bytes, password: bytes | None = None) -> "RSAPrivateKey":
        return cls(key=serialization.load_pem_private_key(data, password=password))

    def dump(self) -> bytes:
        return self.key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def sign(self, message: bytes) -> bytes:
        return self.key.sign(message, padding.PKCS1v15(), hashes.SHA256())

    def decrypt(self, message: bytes) -> bytes:
        assert len(message) == (self.size // 8)
        return self.key.decrypt(message, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))

    def public_key(self) -> "RSAPublicKey":
        return RSAPublicKey(self.key.public_key())

    @property
    def e(self) -> int:
        return self.key.private_numbers().public_numbers.e

    @property
    def d(self) -> int:
        return self.key.private_numbers().d

    @property
    def n(self) -> int:
        return self.key.private_numbers().public_numbers.n

    @property
    def size(self) -> int:
        return self.key.key_size


class RSAPublicKey:
    """
    Represents a public RSA key
    """

    def __repr__(self):
        return f"{type(self).__name__}(size={self.size}, e={self.e}, n={self.n})"

    def __init__(self, key: rsa.RSAPublicKey):
        self.key = key

    @classmethod
    def load(cls, data: bytes) -> "RSAPublicKey":
        return cls(key=serialization.load_pem_public_key(data))

    def dump(self) -> bytes:
        return self.key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.PKCS1
        )

    def encrypt(self, message: bytes) -> bytes:
        assert len(message) <= self.max_encryptable_message_bytes_size
        return self.key.encrypt(message, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))

    def signature_is_valid(self, message: bytes, signature: bytes) -> bool:
        try:
            self.key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
        except InvalidSignature:
            return False
        else:
           return True

    @property
    def e(self) -> int:
        return self.key.public_numbers().e

    @property
    def n(self) -> int:
        return self.key.public_numbers().n

    @property
    def size(self) -> int:
        return self.key.key_size

    @property
    def max_encryptable_message_bytes_size(self) -> int:
        return (self.size // 8) - 66
