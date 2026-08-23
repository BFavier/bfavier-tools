from typing import Literal, Iterable
from pydantic import BaseModel, Field
from aiobotocore.session import get_session, AioBaseClient


class SQSMessageAttribute(BaseModel):
    data_type: Literal["String", "Number", "Binary"] = Field(..., alias="DataType")
    string_value: str = Field("", alias="StringValue")
    binary_value: bytes = Field(b"", alias="BinaryValue")
    string_list_values: list[str] = Field([], alias="StringListValues")
    binary_list_values: list[bytes] = Field([], alias="BinaryListValues")


class SQSMessage(BaseModel):
    body: str = Field(..., alias="Body")
    message_attributes: dict[str, SQSMessageAttribute] = Field({}, alias="MessageAttributes")


class SQSMessageResponse(SQSMessage):
    message_id: str = Field(..., alias="MessageId")
    receipt_handle: str = Field(..., alias="ReceiptHandle")
    MD5_of_body: str = Field(..., alias="MD5OfBody")
    attributes: dict[str, str] = Field({}, alias="Attributes")
    md5_of_attributes: str | None = Field(None, alias="MD5OfMessageAttributes")


class SimpleQueueService:
    """
    >>> sqs = SimpleQueueService()
    >>> await sqs.open()
    >>> ...
    >>> await sqs.close()

    It can also be used as an async context
    >>> async with SimpleQueueService() as sqs:
    >>>     ...
    """

    def __init__(self):
        self.session = get_session()
        self._client: AioBaseClient | None = None

    async def open(self):
        self._client = await self.session.create_client("sqs").__aenter__()

    async def close(self):
        await self._client.__aexit__(None, None, None)
        self._client = None

    async def __aenter__(self) -> "SimpleQueueService":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    @property
    def client(self) -> object:
        if self._client is None:
            self._raise_not_initialized()
        else:
            return self._client

    async def poll_sqs_message_async(self, queue_url: str, max_messages: int=10, wait_seconds: int=10) -> list[SQSMessageResponse]:
        """
        Poll messages in an sqs queue
        """
        response = await self.client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
        )
        return [SQSMessageResponse(**msg) for msg in response.get("Messages", [])]


    async def delete_sqs_event_async(self, queue_url: str, receipt_handle: str):
        """
        After processing a polled event, you have to delete it, otherwise after 30s, it will appear back in the queue.
        """
        await self.client.delete_message(
            QueueUrl=queue_url,
            ReceiptHandle=receipt_handle,
        )


    async def send_sqs_message_async(self, queue_url: str, message: SQSMessage, delay_seconds: int=0):
        """
        """
        response = await self.client.send_message(
            QueueUrl=queue_url,
            MessageBody=message.Body,
            MessageAttributes={k: v.model_dump(by_alias=True) for k, v in message.MessageAttributes.items()},
            DelaySeconds=delay_seconds,
        )
        return SQSMessageResponse(**response)


    async def batch_send_sqs_messages_async(self, queue_url: str, messages: Iterable[SQSMessage], delay_seconds: int=0, chunk_size: int=10):
        """
        Send the given messages to the SQS queue, by batches of chunk_size, with retry for failures
        """
        iterable = iter(messages)
        message_to_process = True
        batch: dict[str, SQSMessage] = {}
        while message_to_process or len(batch) > 0:
            while len(batch) < chunk_size:
                try:
                    batch[f"msg{len(batch)}"] = next(iterable)
                except StopIteration:
                    message_to_process = False
                    break
            response = await self.client.send_message_batch(
                QueueUrl=queue_url,
                Entries=[
                    {
                        "Id": k,
                        "MessageBody": m.Body,
                        "MessageAttributes": {k: v.model_dump(by_alias=True) for k, v in m.MessageAttributes.items()},
                        "DelaySeconds": delay_seconds,
                    }
                    for k, m in batch.items()
                ]
            )
            for failed in response["Failed"]:
                if failed["SenderFault"]:
                    raise RuntimeError(f"Failed to send a message to SQS queue: '{failed['Message']}'")
            retry = (failed for failed in response["Failed"] if not failed["SenderFault"])
            batch = {f"msg{i}": batch[failed["Id"]] for i, failed in enumerate(retry)}
