from aiobotocore.session import get_session, AioBaseClient


class CloudFormation:
    """
    >>> cdf = CloudFormation()
    >>> await cdf.open()
    >>> ...
    >>> await cdf.close()

    It can also be used as an async context
    >>> async with CloudFormation() as cdf:
    >>>     ...
    """

    def __init__(self):
        self.session = get_session()
        self._client: AioBaseClient | None = None

    async def open(self):
        self._client = await self.session.create_client("cloudformation").__aenter__()

    async def close(self):
        await self._client.__aexit__(None, None, None)
        self._client = None

    async def __aenter__(self) -> "CloudFormation":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    @property
    def client(self) -> AioBaseClient:
        if self._client is None:
            raise RuntimeError(f"{type(self).__name__} object was not awaited on creation, and as such, is not initialized")
        else:
            return self._client


    async def list_stacks_async(self) -> list[str]:
        """
        list existing stacks
        """
        stack_names = []
        results = await self.client.list_stacks()
        while True:
            stack_names.extend([stack["StackName"] for stack in results["StackSummaries"]
                                if stack["StackStatus"] in ["CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"]
                                and stack["StackName"] not in stack_names])
            next_token = results.get("NextToken")
            if next_token is None:
                break
            else:
                results = await self.client.list_stacks(NextToken=next_token)
        return stack_names


    async def get_stack_outputs_async(self, stack: str | None = None) -> dict[str, str]:
        """
        Returns the exported stack outputs. Or all the outputs of all stacks
        """
        if stack is None:
            stacks = await self.list_stacks_async()
        else:
            stacks = [stack]
        stack_outputs = {}
        for stack_name in stacks:
            descriptions = await self.client.describe_stacks(StackName=stack_name)
            stack = descriptions['Stacks'][0]
            for output in stack.get('Outputs', []):
                stack_outputs[output["OutputKey"]] = output["OutputValue"]
        return stack_outputs
