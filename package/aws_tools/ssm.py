import aioboto3
from operator import __and__
from datetime import datetime, UTC
from typing import Literal, AsyncIterable
from pydantic import Field
from aws_tools._snake_base_model import _SnakeBaseModel


class SSMParameter(_SnakeBaseModel):
    """
    Response schema of boto3's 'get_parameter'
    https://docs.aws.amazon.com/boto3/latest/reference/services/ssm/client/get_parameter.html
    """
    arn: str = Field(alias="ARN")
    name: str
    type: str
    value: str
    version: int
    last_modified_date: datetime
    data_type: str
    selector: str | None = None
    source_result: str | None = None


CpuArchitecture = Literal["arm64", "x86_64"]


class SSM:
    """
    An async SSM client
    >>> ssm = SSM()
    >>> await ssm.open()
    >>> ...
    >>> await ssm.close()

    It can also be used as an async context
    >>> async with SSM() as ssm:
    >>>     ...
    """

    def __init__(self, region_name: str | None = None):
        self.session = aioboto3.Session(region_name=region_name)
        self._client = None

    async def open(self):
        self._client = await self.session.client("ssm").__aenter__()

    async def close(self):
        await self.client.__aexit__(None, None, None)
        self._client = None

    async def __aenter__(self) -> "SSM":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def _raise_not_initialized(self):
        raise RuntimeError(f"{type(self).__name__} object was not awaited on creation, and as such, is not initialized")

    @property
    def client(self) -> object:
        if self._client is None:
            self._raise_not_initialized()
        else:
            return self._client
    
    async def get_parameter_async(self, name: str, with_decryption: bool=True) -> SSMParameter:
        """
        """
        response = await self.client.get_parameter(
            Name=name,
            WithDecryption=with_decryption
        )
        return SSMParameter(**response["Parameter"])
    
    async def list_parameters_paginated_async(
            self,
            path: str,
            page_start_token: str | None,
            recursive: bool=False,
            with_decryption: bool=True,
            max_page_size: int=100,
        ) -> tuple[list[SSMParameter], str | None]:
        """
        List parameters at a given path prefix, in a paginated fashion
        """
        response = await self.client.get_parameters_by_path(
            Path=path,
            Recursive=recursive,
            WithDecryption=with_decryption,
            MaxResults=max_page_size,
            NextToken=page_start_token,
        )
        return [SSMParameter(**p) for p in response["Parameters"]], response.get("NextToken")
    
    async def list_parameters_async(
            self,
            path: str,
            recursive: bool=False,
            with_decryption: bool=True,
        ) -> AsyncIterable[SSMParameter]:
        """
        """
        next_page_token = None
        while True:
            page, next_page_token = await self.list_parameters_paginated_async(path, next_page_token, recursive, with_decryption)
            for p in page:
                yield p
            if next_page_token is None:
                break

    async def get_latest_linux_AMI_async(self, architecture: CpuArchitecture, minimal: bool=True) -> str:
        """
        Returns the latest AL2023 AMI image id
        """
        parameter = await self.get_parameter_async(f"/aws/service/ami-amazon-linux-latest/al2023-ami{'-minimal' if minimal else ''}-kernel-default-{architecture}")
        return parameter.value

    async def get_latest_NVIDIA_AMI_async(self, architecture: CpuArchitecture) -> str:
        """
        Return the latest NVIDIA-driver AMI
        """
        parameter = await self.get_parameter_async(f"/aws/service/deeplearning/ami/{architecture}/base-oss-nvidia-driver-gpu-amazon-linux-2023/latest/ami-id")
        return parameter.value

    async def get_latest_ECS_AMI_async(self, architecture: CpuArchitecture) -> str:
        """
        returns the latest ECS optimized AMI
        """
        parameter = await self.get_parameter_async(f"/aws/service/ecs/optimized-ami/amazon-linux-2023/{'arm64/' if architecture == "arm64" else ''}recommended/image_id")
        return parameter.value
