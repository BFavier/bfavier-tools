import json
from base64 import b64decode, b64encode
from json.decoder import JSONDecodeError
from typing import Literal, Any, Annotated, TypeVar, Self, Union
from pydantic import BaseModel, Field, BeforeValidator, SerializerFunctionWrapHandler, SerializationInfo
from pydantic.functional_serializers import WrapSerializer


def base64_serializer(value: bytes, handler: SerializerFunctionWrapHandler, info: SerializationInfo) -> bytes | str:
    """
    Serialize bytes as base64 string for "json" dump mode, keep as bytes for "python" dump mode
    """
    if info.mode == "json":
        return b64encode(value).decode()
    else:
        return value


A = TypeVar("A")


def _add_nullables(x: A | None, y: A | None, zero: A) -> A | None:
    """
    Sum two nullable objects
    """
    return None if (x is None and y is None) else (x or zero) + (y or zero)


# Custom type for bytes that auto-encodes/decodes base64
Base64Bytes = Annotated[
    bytes,
    WrapSerializer(base64_serializer, return_type=bytes | str),
    BeforeValidator(lambda x: b64decode(x) if isinstance(x, str) else x)
]


class BedrockInferenceConfig(BaseModel):
    """
    https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InferenceConfiguration.html
    """
    maxTokens: int | None = None
    temperature: float | None = None
    topP: float | None = None
    stopSequences: list[str] | None = None


class BedrockContentBlock(BaseModel):
    """
    https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ContentBlock.html
    """

    class S3Location(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_S3Location.html
        """
        uri: str

    class DocumentBlock(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_DocumentBlock.html
        """

        class DocumentSource(BaseModel):
            """
            https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_DocumentSource.html
            """

            bytes: Base64Bytes | None = None
            s3Location: Union["BedrockContentBlock.S3Location", None] = None
            text: str | None = None

        name: str
        source: DocumentSource
        format: Literal["pdf", "csv", "doc", "docx", "xls", "xlsx", "html", "txt", "md"]

    class Image(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ImageBlock.html
        """

        class ImageSource(BaseModel):
            """
            https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ImageSource.html
            """
            bytes: Base64Bytes | None = None
            s3Location: Union["BedrockContentBlock.S3Location", None] = None

        format: Literal["png", "jpeg", "gif", "webp"]
        source: ImageSource

        def __iadd__(self, other: "BedrockConverseStreamEventResponse.ContentBlockDeltaEvent.ContentBlockDelta.ImageBlockDelta") -> Self:
            self.source.bytes = _add_nullables(self.source.bytes, other.imageSource.bytes, b"")
            self.source.s3Location = self.source.s3Location or other.imageSource.s3Location
            return self

    class ToolUse(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ToolUseBlock.html
        """
        input: dict | str | None = None  # str type only for incompletely generated input
        name: str
        toolUseId: str

        def __iadd__(self, other: "BedrockConverseStreamEventResponse.ContentBlockDeltaEvent.ContentBlockDelta.ToolUseBlockDelta") -> Self:
            self.input = _add_nullables(self.input, other.input, "")
            try:
                self.input = json.loads(self.input)
            except JSONDecodeError as e:
                pass
            return self

    class ToolResult(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ToolResultBlock.html
        """

        class ToolResultContent(BaseModel):
            """
            https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ToolResultContentBlock.html
            """
            json_: dict | None = Field(None, alias="json")
            text: str | None = None
            document: Union["BedrockContentBlock.DocumentBlock", None] = None
            image: Union["BedrockContentBlock.Image", None] = None

        content: list[ToolResultContent]
        toolUseId: str
        status: Literal["success", "error"]

        def __iadd__(self, other: "BedrockConverseStreamEventResponse.ContentBlockDeltaEvent.ContentBlockDelta.ToolResultBlockDelta") -> Self:
            self.content.append(
                BedrockContentBlock.ToolResult.ToolResultContent(
                    json=other.json,
                    text=other.text,
                    image=None,
                    document=None,
                )
            )
            return self

    class ReasoningContentBlock(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ReasoningContentBlock.html
        """

        class ReasoningTextBlock(BaseModel):
            """
            https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ReasoningTextBlock.html
            """
            text: str
            signature: str | None = None

        reasoningText: ReasoningTextBlock | None = None
        redactedContent: Base64Bytes | None = None

        def __iadd__(self, other: "BedrockConverseStreamEventResponse.ContentBlockDeltaEvent.ContentBlockDelta.ReasoningContentBlockDelta") -> Self:
            self.redactedContent=_add_nullables(self.redactedContent, other.redactedContent, b"")
            self.reasoningText.text=_add_nullables(self.reasoningText.text, other.text, "")
            self.reasoningText.signature = self.reasoningText.signature or other.signature
            return self

    class CitationsContentBlock(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_CitationsContentBlock.html
        """

        class Citation(BaseModel):
            """
            https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Citation.html
            """

            class CitationLocation(BaseModel):
                """
                https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_CitationLocation.html
                TODO: complete deeper nested mapping of the object
                """
                documentChar: Any | None = None
                documentChunk: Any | None = None
                documentPage: Any | None = None
                searchResultLocation: Any | None = None
                web: Any | None = None

            class CitationSourceContent(BaseModel):
                """
                https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_CitationSourceContent.html
                """
                text: str | None = None

            location: CitationLocation | None = None
            source: str | None = None
            sourceContent: CitationSourceContent | None = None
            title: str | None = None

        class CitationGeneratedContent(BaseModel):
            """
            https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_CitationGeneratedContent.html
            """
            text: str

        citations: list[Citation] | None = None
        content: CitationGeneratedContent | None = None

    document: DocumentBlock | None = None
    image: Image | None = None
    reasoningContent: ReasoningContentBlock | None = None
    text: str | None = None
    toolUse: ToolUse | None = None
    toolResult: ToolResult | None = None
    citationsContent: CitationsContentBlock | None = None

    def __iadd__(self, other: "BedrockConverseStreamEventResponse.ContentBlockDeltaEvent.ContentBlockDelta") -> Self:
        if self.citationsContent is not None:
            if other.citation is not None:
                self.citationsContent.citations.append(
                    BedrockContentBlock.CitationsContentBlock.Citation(
                        location=other.citation.location,
                        source=other.citation.source,
                        sourceContent=BedrockContentBlock.CitationsContentBlock.Citation.CitationSourceContent(text=other.citation.sourceContent.text),
                        title=other.citation.title
                    )
                )
            self.citationsContent.content = _add_nullables(self.citationsContent.content, other.text, "")
        elif self.image is not None:
            self.image += other.image
        elif self.reasoningContent is not None:
            self.reasoningContent += other.reasoning
        elif self.toolResult is not None:
            self.toolResult += other.toolResult
        elif self.toolUse is not None:
            self.toolUse += other.toolUse
        else:
            self.text = _add_nullables(self.text, other.text, "")
        return self


class BedrockSystemContentBlock(BaseModel):
    """
    https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_SystemContentBlock.html
    """

    class CachePointBlock(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_CachePointBlock.html
        """
        type: Literal["default"] = "type"
        ttl: Literal["5m", "1h"] | None = None
    
    class GuardrailConverseContentBlock(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_GuardrailConverseContentBlock.html
        TODO: I did not dig deeper yet in the structure
        """
        image: Any
        text: Any

    cachePoint: CachePointBlock | None = None
    guardContent: GuardrailConverseContentBlock | None = None
    text: str | None = None


class BedrockMessage(BaseModel):
    """
    https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Message.html
    """
    role: Literal["user", "assistant"]
    content: list[BedrockContentBlock]


class ToolConfig(BaseModel):
    """
    https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ToolConfiguration.html
    """

    class Tool(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Tool.html
        """

        class ToolSpec(BaseModel):
            """
            https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ToolSpecification.html
            """

            class ToolInputSchema(BaseModel):
                """
                https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ToolInputSchema.html
                """
                json_: dict = Field(..., alias="json")  # JSON schema

            inputSchema: ToolInputSchema
            name: str
            description: str | None = None

        toolSpec: ToolSpec

    tools: list[Tool]


class BedrockConverseRequest(BaseModel):
    """
    https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html#API_runtime_Converse_RequestBody
    """
    modelId: str
    messages: list[BedrockMessage]
    inferenceConfig: BedrockInferenceConfig | None = None
    system: list[BedrockSystemContentBlock] | None = None
    toolConfig: ToolConfig | None = None

    @property
    def dump(self) -> dict:
        """
        Dump into json serialisable object, making sure that document data are bytes
        """
        payload = self.model_dump(mode="python", by_alias=True, exclude_none=True)
        return payload


class BedrockConverseResponse(BaseModel):
    """
    https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html#API_runtime_Converse_ResponseElements
    """

    class TokenUsage(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_TokenUsage.html
        """
        inputTokens: int
        outputTokens: int
        totalTokens: int

        def __iadd__(self, other: Self) -> Self:
            self.inputTokens += other.inputTokens
            self.outputTokens += other.outputTokens
            self.totalTokens += other.totalTokens
            return self
        
        def __add__(self, other: Self) -> Self:
            copied = self.model_copy()
            copied += other
            return copied

    class BedrockConverseMetrics(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ConverseMetrics.html
        """
        latencyMs: int

    class BedrockPerformanceConfiguration(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_PerformanceConfiguration.html
        """
        latencyOptimized: Literal["standard ", "optimized"] | None = None

    class BedrockServiceTier(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ServiceTier.html
        """
        tier: Literal["priority", "default", "flex", "reserved"]

    class BedrockConverseTrace(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ConverseTrace.html
        """

        class BedrockGuardrailTrace(BaseModel):
            """
            https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_GuardrailTraceAssessment.html
            """

            class BedrockGuardrailAssesment(BaseModel):
                """
                https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_GuardrailAssessment.html
                this is getting deep, I give up mapping this object for now
                """
                appliedGuardrailDetails : Any | None = None
                automatedReasoningPolicy : Any | None = None
                contentPolicy : Any | None = None
                contextualGroundingPolicy : Any | None = None
                invocationMetrics : Any | None = None
                sensitiveInformationPolicy : Any | None = None
                topicPolicy : Any | None = None
                wordPolicy : Any | None = None

            actionReason : str | None = None
            inputAssessment : dict[str, list[BedrockGuardrailAssesment]] | None = None
            modelOutput : list[str] | None = None
            outputAssessments : dict[str, list[BedrockGuardrailAssesment]] | None = None

        class BedrockPromptRouterTrace(BaseModel):
            """
            https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_PromptRouterTrace.html
            """
            invokedModelId: str | None = None

        guardrail: str | None = None
        promptRouter: BedrockPromptRouterTrace | None = None

    class BedrockConverseOutput(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ConverseOutput.html
        """
        message: BedrockMessage

    metrics: BedrockConverseMetrics
    output: BedrockConverseOutput
    stopReason: Literal["end_turn", "tool_use", "max_tokens", "stop_sequence", "guardrail_intervened", "content_filtered", "malformed_model_output", "malformed_tool_use", "model_context_window_exceeded"]
    usage: TokenUsage
    additionalModelResponseFields: dict | None = None
    performanceConfig: BedrockPerformanceConfiguration | None = None
    serviceTier: BedrockServiceTier | None = None
    trace: BedrockConverseTrace | None = None


class BedrockConverseStreamEventResponse(BaseModel):
    """
    https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ConverseStream.html#API_runtime_ConverseStream_ResponseElements
    """

    class ContentBlockStartEvent(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ContentBlockStartEvent.html
        """

        class ContentBlockStart(BaseModel):
            """
            https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ContentBlockStart.html
            """

            class ImageBlockStart(BaseModel):
                """
                https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ImageBlockStart.html
                """
                format: Literal["png", "jpeg", "gif", "webp"]

            class ToolResultBlockStart(BaseModel):
                """
                https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ToolResultBlockStart.html
                """
                toolUseId: str
                status: Literal["error", "success"]
                type: str | None = None
            
            class ToolUseBlockStart(BaseModel):
                """
                https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ToolUseBlockStart.html
                """
                name: str
                toolUseId: str
                type: Literal["server_tool_use"] = "server_tool_use"

            image: ImageBlockStart | None = None
            toolUse: ToolUseBlockStart | None = None
            toolResult: ToolResultBlockStart | None = None

            def as_initial_content_block(self) -> BedrockContentBlock:
                """
                Returns a BedrockContentBlock
                """
                return BedrockContentBlock(
                    document=None,
                    image=None if self.image is None else BedrockContentBlock.Image(format=self.image.format, source=BedrockContentBlock.Image.ImageSource()),
                    text=None,
                    toolUse=None if self.toolUse is None else BedrockContentBlock.ToolUse(toolUseId=self.toolUse.toolUseId, name=self.toolUse.name, input=None),
                    toolResult=None if self.toolResult is None else BedrockContentBlock.ToolResult(toolUseId=self.toolResult.toolUseId, status=self.toolResult.status, content=list())
                )
    
        start: ContentBlockStart
        contentBlockIndex: int

    class ContentBlockDeltaEvent(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ContentBlockDeltaEvent.html
        """

        class ContentBlockDelta(BaseModel):
            """
            https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ContentBlockDelta.html
            """

            class ToolUseBlockDelta(BaseModel):
                """
                https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ToolUseBlockDelta.html
                """
                input: str

            class ToolResultBlockDelta(BaseModel):
                """
                https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ToolResultBlockDelta.html
                """
                json_: dict | None = Field(None, alias="json")
                text: str | None = None
            
            class ReasoningContentBlockDelta(BaseModel):
                """
                https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ReasoningContentBlockDelta.html
                """
                redactedContent: Base64Bytes | None = None
                text: str | None = None
                signature: str | None = None
            
            class ImageBlockDelta(BaseModel):
                """
                https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ImageBlockDelta.html
                """

                class ErrorBlock(BaseModel):
                    """
                    https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ErrorBlock.html
                    """
                    message: str

                error: Any | None = None
                imageSource: BedrockContentBlock.Image.ImageSource | None = None

            class CitationDelta(BaseModel):
                """
                https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_CitationsDelta.html
                """

                class CitationSourceContentDelta(BaseModel):
                    """
                    https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_CitationSourceContentDelta.html
                    """
                    text: str | None = None

                location: BedrockContentBlock.CitationsContentBlock.Citation.CitationLocation | None = None
                source: str | None = None
                sourceContent: CitationSourceContentDelta | None = None
                title: str | None = None

            citation: CitationDelta | None = None
            image: ImageBlockDelta | None = None
            reasoning: ReasoningContentBlockDelta | None = None
            text: str | None = None
            toolResult: ToolResultBlockDelta | None = None
            toolUse: ToolUseBlockDelta | None = None

        delta: ContentBlockDelta
        contentBlockIndex: int

    class ContentBlockStopEvent(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ContentBlockStopEvent.html
        """
        contentBlockIndex: int

    class MessageStartEvent(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_MessageStartEvent.html
        """
        role: Literal["user", "assistant"]

    class MessageStopEvent(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_MessageStopEvent.html
        """
        stopReason: Literal["end_turn", "tool_use", "max_tokens", "stop_sequence", "guardrail_intervened", "content_filtered", "malformed_model_output", "malformed_tool_use", "model_context_window_exceeded"]
        additionalModelResponseFields: dict | None = None

    class Metadata(BaseModel):
        """
        https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ConverseStreamMetadataEvent.html
        """
        metrics: BedrockConverseResponse.BedrockConverseMetrics
        usage: BedrockConverseResponse.TokenUsage
        performanceConfig: Any | None = None
        serviceTier: BedrockConverseResponse.BedrockServiceTier | None = None
        trace: BedrockConverseResponse.BedrockConverseTrace | None = None

    contentBlockDelta: ContentBlockDeltaEvent | None = None
    contentBlockStart: ContentBlockStartEvent | None = None
    contentBlockStop: ContentBlockStopEvent | None = None
    messageStart: MessageStartEvent | None = None
    messageStop: MessageStopEvent | None = None
    metadata: Metadata | None = None

    def content(self) -> ContentBlockDeltaEvent | ContentBlockStartEvent | ContentBlockStopEvent | MessageStartEvent | MessageStopEvent | Metadata | None:
        for name, value in self:
            if value is not None:
                return value
        return None
