from collections import defaultdict
from typing import Any, Type, TypeVar, AsyncIterable
from pydantic import BaseModel
from aws_tools.bedrock.client import Bedrock
from aws_tools.bedrock.converse.entities import BedrockConverseRequest, BedrockConverseResponse, BedrockConverseStreamEventResponse, ToolConfig, BedrockMessage, BedrockContentBlock, BedrockInferenceConfig, BedrockSystemContentBlock


class AgentTool(BaseModel):
    """
    Derive this base class to implement a tool that LLMs can call.
    The description of the tool must be the class docstring.
    The arguments to be provided by the LLM must be fields of the class, the description of which is described with pydantic's 'argument = Field(..., description="the tool argument description")'.
    """

    async def __call__(self, **secrets) -> Any:
        """
        Any documentation here is invisible to the LLM.
        The implementation of the actual tool is in the class' __call__ method.
        In addition to the tool args that are fields of this object,
        any additional kwarg passed to the __call__ method can be used for the logic while staying hidden from the LLM
        """
        raise NotImplementedError()
    
    @classmethod
    def definition(cls) -> ToolConfig.Tool:
        """
        """
        return ToolConfig.Tool(
            toolSpec=ToolConfig.Tool.ToolSpec(
                inputSchema=ToolConfig.Tool.ToolSpec.ToolInputSchema(json=cls.model_json_schema()),
                name=cls.__name__,
                description="\n".join(s.strip() for s in cls.__doc__.split("\n") if len(s.strip()) > 0) if cls.__doc__ is not None else None
            )
        )


T = TypeVar("T", bound=Type[AgentTool])


class Agent:
    """
    Derive this base class agent is an LLM with tools registered
    """

    def __init_subclass__(cls, **kwargs):
        """
        Each derived class have a distinct set of 'tools' and 'tool_config' objects
        """
        super().__init_subclass__(**kwargs)
        cls.tools: dict[str, Type[AgentTool]] = {}
        cls.tool_config: ToolConfig | None = None

    def __init__(self, bedrock_client: Bedrock, model_id: str, system_prompt: str | None = None):
        self.bedrock_client = bedrock_client
        self.model_id = model_id
        self.system_prompt = system_prompt

    @classmethod
    def register_tool(cls, new_tool: T) -> T:
        """
        A decorator to apply on top of new tool to register into an agent class
        """
        cls.tools[new_tool.__name__] = new_tool
        cls.tool_config = ToolConfig(
            tools=[T.definition() for T in cls.tools.values()]
        )
        return new_tool

    async def converse_async(self, history: list[BedrockMessage], inference_config: BedrockInferenceConfig = BedrockInferenceConfig(), tool_secrets: dict[str, dict]=defaultdict(dict)) -> tuple[list[BedrockMessage], BedrockConverseResponse.TokenUsage]:
        """
        Returns a response from the LLM.
        """
        inference_config = inference_config.model_copy()
        token_usage = BedrockConverseResponse.TokenUsage(inputTokens=0, outputTokens=0, totalTokens=0)
        new_messages = 0
        while True:
            payload = BedrockConverseRequest(
                modelId=self.model_id,
                messages=history,
                inferenceConfig=inference_config,
                system=[BedrockSystemContentBlock(text=self.system_prompt)] if self.system_prompt is not None else None,
                toolConfig=self.tool_config
            )
            response = await self.bedrock_client.converse_async(payload)
            new_messages+=1;history.append(response.output.message)
            token_usage += response.usage
            tool_uses = [block.toolUse for block in response.output.message.content if block.toolUse is not None]
            if inference_config.maxTokens is not None:
                inference_config.maxTokens -= response.usage.outputTokens
            if len(tool_uses) == 0 or (inference_config is not None and inference_config.maxTokens <= 0):
                break
            new_messages+=1;history.append(BedrockMessage(role="user", content=[BedrockContentBlock(toolResult=self._call_tool_async(tool, tool_secrets)) for tool in tool_uses]))
        return history[-new_messages:], token_usage

    async def converse_stream(self, history: list[BedrockMessage], inference_config: BedrockInferenceConfig = BedrockInferenceConfig(), tool_secrets: dict[str, dict]=defaultdict(dict)) -> AsyncIterable[BedrockConverseStreamEventResponse.ContentBlockDeltaEvent.ContentBlockDelta | BedrockConverseResponse.TokenUsage]:
        """
        Stream the response from the LLM, then finally yield the total token usage
        """
        inference_config = inference_config.model_copy()
        token_usage = BedrockConverseResponse.TokenUsage(inputTokens=0, outputTokens=0, totalTokens=0)
        while True:
            payload = BedrockConverseRequest(
                modelId=self.model_id,
                messages=history,
                inferenceConfig=inference_config,
                system=[BedrockSystemContentBlock(text=self.system_prompt)] if self.system_prompt is not None else None,
                toolConfig=self.tool_config
            )
            async for event in self.bedrock_client.converse_stream(payload):
                if isinstance(event, BedrockConverseStreamEventResponse.ContentBlockDeltaEvent.ContentBlockDelta):
                    yield event
            history.append(event.output.message)
            token_usage += event.usage
            tool_uses = [block.toolUse for block in event.output.message.content if block.toolUse is not None]
            if inference_config.maxTokens is not None:
                inference_config.maxTokens -= event.usage.outputTokens
            if len(tool_uses) == 0 or (inference_config is not None and inference_config.maxTokens <= 0):
                break
            history.append(BedrockMessage(role="user", content=[BedrockContentBlock(toolResult=await self._call_tool_async(tool, tool_secrets)) for tool in tool_uses]))
        yield token_usage 

    async def _call_tool_async(self, tool_use: BedrockContentBlock.ToolUse, tool_secrets: dict[str, dict]) -> BedrockContentBlock.ToolResult:
        """
        Call the request tool and return the tool result object
        """
        try:
            Tool = self.tools[tool_use.name]
            tool = Tool(**tool_use.input)
            result = await tool(**tool_secrets[tool_use.name])
        except Exception as e:
            return BedrockContentBlock.ToolResult(
                content=[
                    BedrockContentBlock.ToolResult.ToolResultContent(json={"error_type": type(e).__name__, "error_value": str(e)})
                ],
                toolUseId=tool_use.toolUseId,
                status="error"
            )
        else:
            return BedrockContentBlock.ToolResult(
                content=[
                    BedrockContentBlock.ToolResult.ToolResultContent(json={"result": result})
                ],
                toolUseId=tool_use.toolUseId,
                status="success"
            )
