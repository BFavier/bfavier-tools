import json
from aiobotocore.session import get_session, AioBaseClient


class Firehose:
    """
    >>> f = Firehose()
    >>> await f.open()
    >>> ...
    >>> await f.close()

    It can also be used as an async context
    >>> async with Firehose() as f:
    >>>     ...
    """

    def __init__(self):
        self.session = get_session()
        self._client: AioBaseClient | None = None

    async def open(self):
        self._client = await self.session.create_client("firehose").__aenter__()

    async def close(self):
        await self._client.__aexit__(None, None, None)
        self._client = None

    async def __aenter__(self) -> "Firehose":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    @property
    def client(self) -> AioBaseClient:
        if self._client is None:
            raise RuntimeError(f"{type(self).__name__} object is not initialized")
        else:
            return self._client

    async def save_to_firehose_async(self, serialisable: dict | list | str | int | float | None, firehose_stream: str):
        """
        Save a json serialisable to a firehose stream
        """
        await self.client.put_record(
            DeliveryStreamName=firehose_stream,
            Record={
                "Data": json.dumps(serialisable)+"\n"
            }
        )
