from pydantic import BaseModel, Field
from aiobotocore.session import get_session, AioBaseClient


class CallerIdentity(BaseModel):
    user_id: str = Field(..., alias="UserId")
    account: str = Field(..., alias="Account")
    arn: str = Field(..., alias="Arn")


class SecurityTokenService:
    """
    >>> sts = SecurityTokenService()
    >>> await sts.open()
    >>> ...
    >>> await sts.close()

    It can also be used as an async context
    >>> async with SecurityTokenService() as sts:
    >>>     ...
    """

    def __init__(self):
        self.session = get_session()
        self._client: AioBaseClient | None = None

    async def open(self):
        self._client = await self.session.create_client("sts").__aenter__()

    async def close(self):
        await self._client.__aexit__(None, None, None)
        self._client = None

    async def __aenter__(self) -> "SecurityTokenService":
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
    
    async def get_caller_identity_async(self) -> CallerIdentity:
        return CallerIdentity(**await self.client.get_caller_identity())
