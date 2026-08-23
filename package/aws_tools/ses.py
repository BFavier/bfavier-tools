"""
Defines the payload format for bounce or complaints received by the API hook receives an event linked to an email.
Format documentation found here:
https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-top-level-json-object
You can find some examples here:
https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-examples.html
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal, Union
from aiobotocore.session import get_session, AioBaseClient
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication


class SimpleEmailingService:
    """
    An async client for AWS SES

    >>> ses = SimpleEmailingService()
    >>> await ses.open()
    >>> ...
    >>> await ses.close()

    It can also be used as an async context
    >>> async with SimpleEmailingService() as ses:
    >>>     ...
    """

    def __init__(self):
        self.session = get_session()
        self._client: AioBaseClient | None = None

    async def open(self):
        self._client = await self.session.create_client("ses").__aenter__()

    async def close(self):
        await self._client.__aexit__(None, None, None)
        self._client = None

    async def __aenter__(self) -> "SimpleEmailingService":
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

    async def send_email_async(
            self,
            sender_email: str,
            recipient_emails: list[str],
            subject: str,
            body: str,
            configuration_set: str | None = None,
        ):
        """
        Send an email to the given recipients
        """
        kwargs = {} if configuration_set is None else {"ConfigurationSetName": configuration_set}
        await self.client.send_email(
            Source=sender_email,
            Destination={
                'ToAddresses': recipient_emails,
            },
            Message={
                'Subject': {'Charset': 'UTF-8', 'Data': subject},
                'Body': {'Html': {'Charset': 'UTF-8', 'Data': body},}
            },
            **kwargs
        )


    async def send_raw_email_async(
        self,
        sender_email: str,
        recipient_emails: list[str],
        subject: str,
        text: str | None = None,
        html: str | None = None,
        attachments: dict[str, bytes] = {},
        configuration_set: str | None = None,
    ):
        """
        Send an email with optional file attachments via AWS SES
        """
        # Build MIME email
        msg = MIMEMultipart("mixed" if len(attachments) > 0 else "alternative")
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = ", ".join(recipient_emails)
        # Add email body
        if text is not None and html is not None:
            # multipart/alternative inside multipart/mixed
            alt = MIMEMultipart("alternative")
            alt.attach(MIMEText(text, "plain", "utf-8"))
            alt.attach(MIMEText(html, "html", "utf-8"))
            msg.attach(alt)
        elif text is not None:
            msg.attach(MIMEText(text, "plain", "utf-8"))
        elif html is not None:
            msg.attach(MIMEText(html, "html", "utf-8"))
        # Add attachments if provided
        for file_name, file_content in attachments.items():
            part = MIMEApplication(file_content)
            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=file_name
            )
            msg.attach(part)
        # Send via SES
        kwargs = {} if configuration_set is None else {"ConfigurationSetName": configuration_set}
        response = await self.client.send_raw_email(
            Source=sender_email,
            Destinations=recipient_emails,
            RawMessage={"Data": msg.as_bytes()},
            **kwargs
        )
        return response


class _SESEvent(BaseModel):
    """
    base class for SES related events
    """
    model_config = ConfigDict(populate_by_name=True)


class Mail(BaseModel):
    """
    https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-mail-object
    """

    class Header(BaseModel):
        name: str
        value: str

    class CommonHeaders(BaseModel):
        from_: list[str] = Field(alias="from")
        to: list[str]
        messageId: str
        subject: str

    timestamp: str
    messageId: str
    source: str
    sourceArn: str | None = None
    sendingAccountId: str
    destination: list[str]
    headersTruncated: bool | None = None
    headers: list[Header] | None = None
    commonHeaders: CommonHeaders | None = None


class Recipient(BaseModel):
    """
    https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-complained-recipients
    """
    emailAddress: str


class BounceEvent(_SESEvent):
    """
    https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-bounce-object
    """

    class BounceRecipient(Recipient):
        """
        https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-bounced-recipients
        """
        action: str | None = None
        status: str | None = None
        diagnosticCode: str | None = None

    # for bounce type and subtype meanings, see https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-bounce-types
    bounceType: Literal["Undetermined", "Permanent", "Transient"]
    bounceSubType: Literal["Undetermined", "General", "NoEmail", "Suppressed", "OnAccountSuppressionList", "MailboxFull", "MessageTooLarge", "ContentRejected", "AttachmentRejected"]
    bouncedRecipients: list[BounceRecipient]
    timestamp: str
    feedbackId: str
    remoteMtaIp: str | None = None
    reportingMTA: str | None = None


class ComplaintEvent(_SESEvent):
    """
    https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-complaint-object
    """
    complainedRecipients: list[Recipient]
    timestamp: str
    feedbackId: str
    # for complaint types, see https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-complaint-types
    complaintFeedbackType: Literal["abuse", "auth-failure", "fraud", "not-spam", "other", "virus"]
    userAgent: str | None = None
    complaintFeedbackType: str | None = None
    arrivalDate: str | None = None


class DeliveryEvent(_SESEvent):
    """
    https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-delivery-object
    """
    timestamp: str
    processingTimeMillis: int
    recipients: list[str]
    smtpResponse: str
    reportingMTA: str
    remoteMtaIp: str


class SendEvent(_SESEvent):
    """
    https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-send-object
    """
    pass


class RejectEvent(_SESEvent):
    """
    https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-reject-object
    """
    reason: Literal["Bad content"]


class OpenEvent(_SESEvent):
    """
    https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-open-object
    """
    ipAddress: str
    timestamp: str
    userAgent: str


class ClickEvent(_SESEvent):
    """
    https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-click-object
    """
    ipAddress: str
    timestamp: str
    userAgent: str
    link: str
    linkTags: dict[str, list[str]]


class RenderingFailureEvent(_SESEvent):
    """
    https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-failure-object
    """
    templateName: str
    errorMessage: str


class DeliveryDelayEvent(_SESEvent):
    """
    https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-delivery-delay-object
    """

    class DelayedRecipients(BaseModel):
        """
        https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-delivery-delay-object-recipients
        """
        status: str
        diagnosticCode: str

    delayType: Literal["InternalFailure", "General", "MailboxFull", "SpamDetected", "RecipientServerError", "IPFailure", "TransientCommunicationFailure", "BYOIPHostNameLookupUnavailable", "Undetermined", "SendingDeferral"]
    delayedRecipients: list[DelayedRecipients]
    expirationTime: str
    timestamp: str
    reportingMTA: str | None = None


class SubscriptionEvent(_SESEvent):
    """
    https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-subscription-object
    """

    class TopicPreferences(BaseModel):
        """
        """

        class TopicSubscriptionStatus(BaseModel):
            """
            """
            topicName: str
            subscriptionStatus: Literal["OptIn", "OptOut"]

        unsubscribeAll: bool
        topicSubscriptionStatus: list[TopicSubscriptionStatus]
        topicDefaultSubscriptionStatus: Literal["OptIn", "OptOut"] | None = None

    contactList: str
    timestamp: str
    source: str
    newTopicPreferences: TopicPreferences
    oldTopicPreferences: TopicPreferences


class SESEmailEvent(_SESEvent):
    """
    https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html#event-publishing-retrieving-sns-contents-top-level-json-object
    """
    eventType: Literal["Bounce", "Complaint", "Delivery", "Send", "Reject", "Open", "Click", "Rendering Failure", "DeliveryDelay", "Subscription"]
    mail: Mail
    bounce: BounceEvent | None = None
    complaint: ComplaintEvent | None = None
    delivery: DeliveryEvent | None = None
    send: SendEvent | None = None
    reject: RejectEvent | None = None
    open: OpenEvent | None = None
    click: ClickEvent | None = None
    failure: RenderingFailureEvent | None = None
    deliveryDelay: DeliveryDelayEvent | None = None
    subscription: SubscriptionEvent | None = None
