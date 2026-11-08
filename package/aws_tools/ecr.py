import base64
from datetime import datetime, UTC, timedelta
from typing import timedelta
from dataclasses import dataclass
from aiobotocore.session import get_session, AioBaseClient


class ElasticContainerRegistry:
    """
    >>> ecr = ElasticContainerRegistry()
    >>> await ecr.open()
    >>> ...
    >>> await ecr.close()

    It can also be used as an async context
    >>> async with ElasticContainerRegistry() as ecr:
    >>>     ...
    """


    @dataclass
    class AuthorizationToken:
        token: str
        endpoint: str
        expires_at: datetime

        def _get_username_and_password(self) -> tuple[str, str]:
            username, password = base64.b64decode(self.token).decode().split(":", 1)

        @property
        def username(self) -> str:
            username, password = self._get_username_and_password()
            return username

        @property
        def password(self) -> str:
            username, password = self._get_username_and_password()
            return password


    def __init__(self):
        self.session = get_session()
        self._cached_authorization_token = ElasticContainerRegistry.AuthorizationToken(token="", endpoint="", expires_at=datetime(year=1900, month=1, day=1, tzinfo=UTC))
        self._client: AioBaseClient | None = None

    async def open(self):
        self._client = await self.session.create_client("ecr").__aenter__()

    async def close(self):
        await self._client.__aexit__(None, None, None)
        self._client = None

    async def __aenter__(self) -> "ElasticContainerRegistry":
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

    async def list_repositories_async(self) -> list[str]:
        """
        Return all existing repository names
        """
        paginator = self.client.get_paginator('describe_repositories')
        return [repo["repositoryName"] async for page in paginator.paginate() for repo in page['repositories']]

    async def list_image_tags_async(self, repository_name: str) -> dict[str, datetime]:
        """
        Return a dict of {tag: image_pushed_timestamp}
        """
        paginator = self.client.get_paginator("describe_images")
        results = {}
        async for page in paginator.paginate(repositoryName=repository_name):
            for image in page["imageDetails"]:
                pushed_at = image["imagePushedAt"]
                for tag in image.get("imageTags", []):
                    results[tag] = pushed_at
        return results

    async def get_authorization_token_async(self) -> ElasticContainerRegistry.AuthorizationToken:
        """
        Authenticate to ECR, similar to 'aws ecr get-authorization-token' with the aws CLI
        Returns (username, password, endpoint, expires_at)
        """
        response = await self.client.get_authorization_token()
        auth = response["authorizationData"][0]
        return ElasticContainerRegistry.AuthorizationToken(
            token=auth["authorizationToken"],
            endpoint=auth["proxyEndpoint"],
            expires_at=datetime.fromisoformat(auth["expiresAt"])
        )

    async def get_authorization_token_cached_async(self) -> tuple[ElasticContainerRegistry.AuthorizationToken, bool]:
        """
        Same as above, but fetchs a new one only if the cached one is close to expiring
        Also returns whether the returned token is from cache, as a boolean.
        """
        cached = True
        if datetime.now(UTC) + timedelta(minutes=1) >= self._cached_authorization_token.expires_at:
            self._cached_authorization_token = await self.get_authorization_token_async()
            cached = False
        return self._cached_authorization_token, cached
