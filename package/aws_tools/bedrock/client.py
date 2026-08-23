import asyncio
import aioboto3
from typing import AsyncIterable
from aws_tools.bedrock.converse.entities import BedrockConverseRequest, BedrockConverseResponse, BedrockConverseStreamEventResponse, BedrockMessage, BedrockContentBlock


class Bedrock:
    """
    Bedrock client that handles async converse API
    """

    def __init__(self, region: str | None = None):
        self.session = aioboto3.Session()
        if region is None:
            self._region = self.session._session.get_config_variable("region")
        else:
            self._region = region
        self._client = None

    async def open(self):
        self._client = await self.session.client("bedrock-runtime", region_name=self._region).__aenter__()

    async def close(self):
        await self._client.__aexit__(None, None, None)
        self._client = None

    async def __aenter__(self) -> "Bedrock":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def converse_async(self, payload: BedrockConverseRequest) -> BedrockConverseResponse:
        return BedrockConverseResponse(**await self._client.converse(**payload.model_dump(mode="python", exclude_none=True, by_alias=True)))

    async def converse_stream(self, payload: BedrockConverseRequest) -> AsyncIterable[BedrockConverseStreamEventResponse.ContentBlockDeltaEvent.ContentBlockDelta | BedrockConverseResponse]:
        """
        Stream the LLM text answer to a request, then finally yield the complete response object
        """
        response = await self._client.converse_stream(**payload.model_dump(mode="python", exclude_none=True, by_alias=True))
        message_start: BedrockConverseStreamEventResponse.MessageStartEvent | None = None
        block_content_by_index: dict[int, BedrockContentBlock] = {}
        block_delta_by_index: dict[int, list[BedrockConverseStreamEventResponse.ContentBlockDeltaEvent.ContentBlockDelta]] = {}
        message_stop: BedrockConverseStreamEventResponse.MessageStopEvent | None = None
        metadata: BedrockConverseStreamEventResponse.Metadata | None = None
        # loop on events
        async for event in response["stream"]:
            content = BedrockConverseStreamEventResponse(**event).content()
            if isinstance(content, BedrockConverseStreamEventResponse.MessageStartEvent):
                message_start = content
            if isinstance(content, BedrockConverseStreamEventResponse.ContentBlockStartEvent):
                block_content_by_index[content.contentBlockIndex] = content.start.as_initial_content_block()
            elif isinstance(content, BedrockConverseStreamEventResponse.ContentBlockDeltaEvent):
                if content.delta.text is not None:
                    yield content.delta
                block_delta_by_index.setdefault(content.contentBlockIndex, list()).append(content.delta)
            elif isinstance(content, BedrockConverseStreamEventResponse.Metadata):
                metadata = content
            elif isinstance(content, BedrockConverseStreamEventResponse.MessageStopEvent):
                message_stop = content
            else:
                await asyncio.sleep(0.0)
        # aggregate all the nlobks delta
        for i, block in block_content_by_index.items():
            for delta in block_delta_by_index[i]:
                block += delta
        # yield the final response and exit
        yield BedrockConverseResponse(
            metrics=metadata.metrics,
            output=BedrockConverseResponse.BedrockConverseOutput(
                message=BedrockMessage(
                    role=message_start.role,
                    content=[block for _, block in sorted(block_content_by_index.items())]
                )
            ),
            stopReason=message_stop.stopReason,
            usage=metadata.usage,
        )
