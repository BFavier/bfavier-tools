from aiobotocore.session import get_session, AioBaseClient
from datetime import datetime


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

    def __init__(self):
        self.session = get_session()
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
