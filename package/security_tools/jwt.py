import json
import base64
from typing import Literal, TypeVar, Generic, Annotated, Type
from datetime import datetime, timedelta, UTC
from pydantic import BaseModel, field_validator, field_serializer
from datetime import datetime, UTC
from security_tools.rsa import RSAPrivateKey, RSAPublicKey


T = TypeVar("T")


class JsonWebToken(BaseModel, Generic[T]):
    """
    Json Web Token implementation
    """

    class Header(BaseModel):
        """
        Header of JWT
        """
        alg: Literal["RS256"]
        typ: Literal["JWT"]

    class Payload(BaseModel, Generic[T]):
        """
        Message stored in JWT
        """

        @field_validator("iat", "exp", mode="before")
        def int_to_datetime(cls, v: int | None) -> datetime | None:
            if v is None:
                return None
            if isinstance(v, int):
                return datetime.fromtimestamp(v, tz=UTC)
            return v

        @field_serializer("iat", "exp")
        def datetime_to_int(self, dt: datetime | None) -> int | None:
            if dt is None:
                return None
            return int(dt.timestamp())

        iat: Annotated[datetime, "issued-at timestamp"]
        exp: Annotated[datetime | None, "expires timestamp"]
        data: T

    header: Header
    payload: Payload[T]
    signature: str

    @classmethod
    def _part_fingerprint(cls, obj: BaseModel) -> str:
        """
        Returns the fingerprint of one part of the JWT
        """
        return cls._urlsafe_b64encode(json.dumps(obj.model_dump(mode="json"), sort_keys=True).encode())

    @classmethod
    def _fingerprint(cls, header: Header, payload: Payload) -> str:
        """
        Return the JWT's fingerprint (to be signed)
        """
        return (cls._part_fingerprint(header) + "." + cls._part_fingerprint(payload))

    @classmethod
    def _sign(cls, header: Header, payload: Payload, encryption: RSAPrivateKey) -> bytes:
        """
        Sign the given message
        """
        if isinstance(encryption, RSAPrivateKey):
            return encryption.sign(cls._fingerprint(header, payload).encode())
        else:
            raise ValueError(f"Alg type is not yet suported")

    @staticmethod
    def _urlsafe_b64encode(input: bytes) -> str:
        """
        urlsafe base64 encode
        """
        return base64.urlsafe_b64encode(input).rstrip(b"=").decode()

    @staticmethod
    def _urlsafe_b64decode(output: str) -> bytes:
        """
        urlsafe base64 decode
        """
        output = output + "=" * (-len(output) % 4)
        return base64.urlsafe_b64decode(output)

    @classmethod
    def generate(cls, data: T, validity_seconds: int | None, encryption: RSAPrivateKey) -> "JsonWebToken[T]":
        """
        Generate and sign a JWT
        """
        now = datetime.now(UTC).replace(microsecond=0)
        if isinstance(encryption, RSAPrivateKey):
            alg = "RS256"
        else:
            raise ValueError("Unexpected encryption key type")
        header = JsonWebToken.Header(alg=alg, typ="JWT")
        payload = cls.Payload(iat=now, exp=None if validity_seconds is None else now+timedelta(seconds=validity_seconds), data=data)
        return JsonWebToken(
            header=header,
            payload=payload,
            signature=cls._urlsafe_b64encode(cls._sign(header, payload, encryption))
        )

    @classmethod
    def load(cls, string: str, payload_data_type: Type[T] | None = None) -> "JsonWebToken[T]":
        """
        Load a JWT from a dump
        """
        header, payload, signature = string.split(".")
        header = JsonWebToken.Header(**json.loads(cls._urlsafe_b64decode(header).decode()))
        payload = JsonWebToken.Payload[T](**json.loads(cls._urlsafe_b64decode(payload).decode()))
        if payload_data_type is not None:
            payload.data = payload_data_type(**payload.data)
        return JsonWebToken(header=header, payload=payload, signature=signature)

    def dump(self) -> str:
        """
        """
        x = self._part_fingerprint(self.header)
        y = self._part_fingerprint(self.payload)
        z = self.signature
        return f"{x}.{y}.{z}"

    def expired(self) -> bool:
        """
        Returns whether the JWT is expired
        """
        if self.payload.exp is None:
            return False
        else:
            return datetime.now(UTC) > self.payload.exp

    def signature_is_valid(self, decryption_key: RSAPublicKey) -> bool:
        """
        Returns whether the JWT signature is valid
        """
        return decryption_key.signature_is_valid(self._fingerprint(self.header, self.payload).encode(), self._urlsafe_b64decode(self.signature))
