"""
Here below the documentation of the expected payload format for the API route handling SNS topic subscription :
https://docs.aws.amazon.com/sns/latest/dg/sns-message-and-json-formats.html
"""
import base64
import aiohttp
from aiobotocore.session import get_session, AioBaseClient
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.x509 import load_pem_x509_certificate, Certificate
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature
from urllib.parse import urlparse
from pydantic import BaseModel, TypeAdapter
from typing import Literal, Annotated, Union


# custome sns headers, dcoumented here: https://docs.aws.amazon.com/sns/latest/dg/http-header.html
HEADERS = [
    "x-amz-sns-message-type",  # 'Notification', 'SubscriptionConfirmation', 'UnsubscribeConfirmation'
    "x-amz-sns-message-id",  # '165545c9-2a5c-472c-8df2-7ff2be2b3b1b3'
    "x-amz-sns-topic-arn",  # 'arn:aws:sns:us-west-2:123456789012:MyTopic'
    "x-amz-sns-subscription-arn"  # 'arn:aws:sns:us-west-2:123456789012:MyTopic:2bcfbf39-05c3-41de-beaa-fcfcc21c8f55'
]


class _SNSEvent(BaseModel):
    """
    Base class for SNS events
    """
    Type: str
    TopicArn: Annotated[str, "arn:aws:sns:us-west-2:123456789012:MyTopic"]
    MessageId: Annotated[str, "165545c9-2a5c-472c-8df2-7ff2be2b3b1b"]
    Message: Annotated[str, ""]
    Timestamp: Annotated[str, "2012-04-26T20:06:41.581Z"]
    SignatureVersion: Annotated[str, "1"]
    Signature: Annotated[str, "EXAMPLEHXgJm..."]
    SigningCertURL: Annotated[str, "https://sns.us-west-2.amazonaws.com/SimpleNotificationService-f3ecfb7224c7233fe7bb5f59f96de52f.pem"]


class SNSSubscriptionConfirmationRequest(_SNSEvent):
    """
    https://docs.aws.amazon.com/sns/latest/dg/http-subscription-confirmation-json.html
    """
    Type: Literal["SubscriptionConfirmation"]
    Token: Annotated[str, "2336412f37..."]
    SubscribeURL: Annotated[str, ""]


class SNSNotificationRequest(_SNSEvent):
    """
    https://docs.aws.amazon.com/sns/latest/dg/http-notification-json.html
    """
    Type: Literal["Notification"]
    Subject: Annotated[str, "My First Message"] | None = None


class SNSUnsubscribeRequest(_SNSEvent):
    """
    https://docs.aws.amazon.com/sns/latest/dg/http-unsubscribe-confirmation-json.html
    """
    Type: Literal["UnsubscribeConfirmation"]
    Token: Annotated[str, "2336412f37..."]
    SubscribeURL: Annotated[str, "https://sns.us-west-2.amazonaws.com/?Action=ConfirmSubscription&TopicArn=arn:aws:sns:us-west-2:123456789012:MyTopic&Token=2336412f37fb6..."]


SNSEventsTypes = Union[SNSSubscriptionConfirmationRequest, SNSNotificationRequest, SNSUnsubscribeRequest]
assert set(_SNSEvent.__subclasses__()) == set(SNSEventsTypes.__args__)


def SNSEvent(payload: dict) -> SNSEventsTypes:
    """
    Load an SNSEvent object, with type matching
    """
    return TypeAdapter(SNSEventsTypes).validate_python(payload)


class SimpleNotificationService:
    """
    An async client for AWS SNS

    >>> sns = SimpleNotificationService()
    >>> await sns.open()
    >>> ...
    >>> await sns.close()

    It can also be used as an async context
    >>> async with SimpleNotificationService() as ses:
    >>>     ...
    """

    def __init__(self):
        self.session = get_session()
        self._client: AioBaseClient | None = None

    async def open(self):
        self._client = await self.session.create_client("sns").__aenter__()

    async def close(self):
        await self._client.__aexit__(None, None, None)
        self._client = None

    async def __aenter__(self) -> "SimpleNotificationService":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    @property
    def client(self) -> object:
        if self._client is None:
            raise RuntimeError(f"{type(self).__name__} object is not initialized")
        else:
            return self._client

    async def send_sms_async(self, phone_number: str, message: str):
        """
        Send an SMS to the given phone number (phone number must be in E.164 format)
        """
        await self._client.publish(
            PhoneNumber=phone_number,
            Message=message
        )

    @staticmethod
    def _is_valid_cert_url(cert_url: str) -> bool:
        """
        Verify that the SigningCertURL is a valid AWS URL
        """
        parsed = urlparse(cert_url)
        return (parsed.scheme == "https" and
                parsed.hostname and
                parsed.hostname.endswith(".amazonaws.com"))

    @staticmethod
    def _get_signed_string(message: SNSEventsTypes) -> str:
        """
        Construct the string that was originally signed
        https://docs.aws.amazon.com/sns/latest/dg/sns-verify-signature-of-message-verify-message-signature.html
        """
        if message.Type == "Notification":
            fields_to_sign = ("Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type")
        elif message.Type in ("SubscriptionConfirmation", "UnsubscribeConfirmation"):
            fields_to_sign = ("Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type")
        else:
            raise RuntimeError(f"Unexpected message type '{message.Type}'")
        field_values = [(field, getattr(message, field, None)) for field in fields_to_sign]
        string_to_sign = "".join(f"{field}\n{value}\n" for field, value in field_values if value is not None)
        return string_to_sign

    @staticmethod
    async def _get_signing_certificate_async(cert_url: str) -> Certificate:
        """
        Download the certificate from the SigningCertURL
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(cert_url) as response:
                cert_data = await response.read()
        return load_pem_x509_certificate(cert_data, default_backend())

    @staticmethod
    async def verify_sns_signature_async(body: SNSEventsTypes) -> bool:
        """
        Verify the signature of an SNS message
        https://docs.aws.amazon.com/sns/latest/dg/sns-verify-signature-of-message.html
        """
        if not SimpleNotificationService._is_valid_cert_url(body.SigningCertURL):
            return False
        decoded_signature = base64.b64decode(body.Signature)
        cert = await SimpleNotificationService._get_signing_certificate_async(body.SigningCertURL)
        public_key = cert.public_key()
        if body.SignatureVersion == "1":
            hash = hashes.SHA1()
        elif body.SignatureVersion == "2":
            hash = hashes.SHA256()
        else:
            raise RuntimeError(f"Unexpected signature version '{body.SignatureVersion}'")
        try:
            public_key.verify(
                decoded_signature,
                SimpleNotificationService._get_signed_string(body).encode("utf-8"),
                padding.PKCS1v15(),
                hash
            )
        except InvalidSignature:
            return False
        else:
            return True
