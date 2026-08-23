from datetime import datetime
from pydantic import BaseModel, Field
from aiobotocore.session import get_session, AioBaseClient
from typing import Literal, Iterable, AsyncIterable, Optional
from botocore.exceptions import ClientError


TASK_STATUSES = Literal["PROVISIONING", "PENDING", "RUNNING", "DEPROVISIONING", "STOPPED", "ACTIVATING"]


class Attribute(BaseModel):
    name: str
    value: str | None = None


class Attachment(BaseModel):
    id: str
    type: Literal["ElasticNetworkInterface", "Service Connect", "AmazonElasticBlockStorage"] | str
    status: Literal["PRECREATED", "CREATED", "ATTACHING", "ATTACHED", "DETACHING", "DETACHED", "DELETED", "FAILED"]
    details: list[Attribute]


class NetworkInterface(BaseModel):
    attachmentId: str
    privateIpv4Address: str | None = None
    ipv6Address: str | None = None


class NetworkBinding(BaseModel):
    bindIP: str
    containerPort: int
    hostPort: int
    protocol: Literal["tcp", "udp"]
    containerPortRange: str
    hostPortRange: str


class ManagedAgent(BaseModel):
    lastStartedAt: str
    name: str
    reason: str
    lastStatus: str


class ECSContainer(BaseModel):
    containerArn: str
    taskArn: str
    name: str
    lastStatus: str
    networkInterfaces: list[NetworkInterface]
    cpu: str
    memory: str | None = None
    image: str | None = None
    imageDigest: str | None = None
    runtimeId: str | None = None
    exitCode: int | None = None
    networkBindings: list[NetworkBinding] | None = None
    healthStatus: Literal["HEALTHY", "UNHEALTHY", "UNKNOWN"] | None = None
    reason: str | None = None
    managedAgents: list[ManagedAgent] | None = None
    memoryReservation: str | None = None
    gpuIds: list[str] | None = None


class EnvironmentFile(BaseModel):
    value: str
    type: Literal["s3"]


class ResourceRequirement(BaseModel):
    value: str
    type: Literal["GPU", "InferenceAccelerator"]


class ECSContainerOverride(BaseModel):
    name: str | None = None
    cpu: int | None = None
    memory: int | None = None
    command: list[str] | None = None
    environment: list[Attribute] | None = None
    environmentFiles: list[EnvironmentFile] | None = None
    memoryReservation: int | None = None
    resourceRequirements: list[ResourceRequirement] | None = None


class Overrides(BaseModel):
    containerOverrides: list[ECSContainerOverride]


ECSTaskStatus = Literal["PROVISIONING", "PENDING", "ACTIVATING", "RUNNING", "DEACTIVATING", "STOPPING", "DEPROVISIONING", "STOPPED", "DELETED"]


class ECSTask(BaseModel):
    attachments: list[Attachment]
    attributes: list[Attribute]
    availabilityZone: str
    clusterArn: str
    containerInstanceArn: str | None = None
    containers: list[ECSContainer]
    cpu: str
    createdAt: datetime
    desiredStatus: ECSTaskStatus
    enableExecuteCommand: bool
    group: str
    launchType: Literal["EC2", "FARGATE"]
    lastStatus: ECSTaskStatus
    memory: str
    overrides: dict
    taskArn: str
    taskDefinitionArn: str
    version: int
    connectivity: Literal["CONNECTED", "DISCONECTED"] | None = None
    connectivityAt: datetime | None = None
    pullStartedAt: datetime | None = None
    pullStoppedAt: datetime | None = None
    startedAt: datetime | None = None
    updatedAt: str | None = None


class ECSTaskStateChangeEvent(BaseModel):
    """
    Event on ECS task state change, as captured by event bridge
    https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs_task_events.html
    """
    version: str
    id: str
    detail_type: str = Field(..., alias="detail-type")
    source: str
    account: str
    time: str
    region: str
    resources: list[str]
    detail: ECSTask


class StorageSize(BaseModel):
    sizeInGiB: int


class Tag(BaseModel):
    key: str
    value: str


class ECSTaskDescription(ECSTask):
    """
    The return type from boto3 ecs 'describe_tasks'
    https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs/client/describe_tasks.html
    """
    containers: list[ECSContainer]
    overrides: Overrides
    platformVersion: str
    platformFamily: str
    tags: list[Tag]
    capacityProviderName: Literal["EC2", "FARGATE"] | None = None
    startedBy: str | None = None
    stopCode: Literal["TaskFailedToStart", "EssentialContainerExited", "UserInitiated", "ServiceSchedulerInitiated", "SpotInterruption", "TerminationNotice"] | None = None
    stoppedAt: datetime | None = None
    stoppedReason: str | None = None
    stoppingAt: datetime | None = None
    ephemeralStorage: StorageSize | None = None
    fargateEphemeralStorage: StorageSize | None = None

    def is_starting(self) -> bool:
        return self.lastStatus in {
            "PROVISIONING",
            "PENDING",
            "ACTIVATING",
        }

    def is_running(self) -> bool:
        return self.lastStatus == "RUNNING"

    def is_stopping(self) -> bool:
        return self.lastStatus in {
            "DEACTIVATING",
            "STOPPING",
            "DEPROVISIONING",
        }

    def is_stopped(self) -> bool:
        return self.lastStatus == "STOPPED"


class ECSTaskDefinition(BaseModel):
    taskDefinitionArn: str
    family: str
    revision: int
    networkMode: str
    status: str
    requiresCompatibilities: list[str]
    cpu: str | None = None
    memory: str | None = None
    executionRoleArn: str | None = None
    taskRoleArn: str | None = None
    containerDefinitions: list[dict]
    volumes: list[dict]
    placementConstraints: list[dict]
    runtimePlatform: dict | None = None
    registeredAt: datetime | None = None
    registeredBy: str | None = None


class ElasticContainerService:
    """
    >>> ecs = ElasticContainerService()
    >>> await ecs.open()
    >>> ...
    >>> await ecs.close()

    It can also be used as an async context
    >>> async with ElasticContainerService() as ecs:
    >>>     ...
    """

    def __init__(self):
        self.session = get_session()
        self._client: AioBaseClient | None = None

    async def open(self):
        self._client = await self.session.create_client("ecs").__aenter__()

    async def close(self):
        await self._client.__aexit__(None, None, None)
        self._client = None

    async def __aenter__(self) -> "ElasticContainerService":
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

    async def run_fargate_task_async(
            self,
            cluster_name: str,
            task_definition: str,
            subnet_ids : list[str],
            security_group_ids: list[str],
            fargate_platform_version: str = "LATEST",
            tags: dict = {},
            main_image_name: str = "MainImage",
            disk_GiB_override: int | None = None,
            env_overrides: dict | None = None,
            assign_public_ip: bool = False,
        ) -> ECSTask:
        """
        Run a standalone task on an ECS cluster.
        Returns the running task arn.
        """
        assert (disk_GiB_override is None) or (20 <= disk_GiB_override <= 200)
        container_overrides = {
            "name": main_image_name,
            "environment": [{"name": k, "value": v} for k, v in env_overrides.items()] if env_overrides is not None else None
        }
        container_overrides = {k : v for k, v in container_overrides.items() if v is not None}
        overrides = {}
        if disk_GiB_override is not None and disk_GiB_override > 20:
            overrides["ephemeralStorage"] = {"sizeInGiB": disk_GiB_override}
        if len(container_overrides.keys()) > 1:
            overrides["containerOverrides"] = [container_overrides]
        kwargs = dict(
            cluster=cluster_name,
            taskDefinition=task_definition,
            launchType="FARGATE",
            platformVersion=fargate_platform_version,
            networkConfiguration={
                "awsvpcConfiguration":
                {
                    "subnets": subnet_ids,
                    "securityGroups": security_group_ids,
                    "assignPublicIp": "ENABLED" if assign_public_ip else "DISABLED"
                }
            },
            tags=[{"key": k, "value": v} for k, v in tags.items()]
        )
        if len(overrides.keys()) > 0:
            kwargs["overrides"] = overrides=overrides
        response = await self.client.run_task(**kwargs)
        return ECSTask(**response["tasks"][0])


    async def stop_fargate_task_async(self, cluster_name: str, task_arn: str, reason: str="Stopped by user") -> bool:
        """
        Stops a running ECS Fargate task.
        If the task did not exist, returns False.
        """
        try:
            await self.client.stop_task(
                cluster=cluster_name,
                task=task_arn,
                reason=reason
            )
        except ClientError as e:
            error = e.response["Error"]
            if (error["Code"] == "InvalidParameterException") and ("The referenced task was not found" in error["Message"]):
                return False
            else:
                raise
        return True


    async def get_tasks_async(self, cluster_name: str, task_arns: list[str], chunk_size: int=100) -> dict[str, ECSTaskDescription]:
        """
        Returns the description of the given tasks, by querying aws by batch.
        """
        subset_arns = [task_arns[i:i+chunk_size] for i in range(0, chunk_size)]
        response = []
        for arns in subset_arns:
            if len(arns) > 0:
                response.extend((await self.client.describe_tasks(cluster=cluster_name, tasks=arns, include=["TAGS"]))["tasks"])
        descriptions = {task["taskArn"]: task for task in response}
        return {arn: ECSTaskDescription(**descriptions[arn]) for arn in task_arns if arn in descriptions.keys()}


    async def get_task_async(self, cluster_name: str, task_arn: str) -> ECSTaskDescription | None:
        """
        Returns the description of the given task
        """
        tasks = await self.get_tasks_async(cluster_name, [task_arn])
        return tasks.get(task_arn)


    async def get_task_definition_async(self, task_definition: str) -> ECSTaskDefinition:
        """
        Returns the description of a task definition.

        `task_definition` may be:
        - family
        - family:revision
        - task definition ARN (and not task ARN)
        """
        response = await self.client.describe_task_definition(
            taskDefinition=task_definition,
            include=["TAGS"],
        )
        return ECSTaskDefinition(**response["taskDefinition"])

    async def list_task_definition_arns_async(
        self,
        family_prefix: str,
        status: Literal["ACTIVE", "INACTIVE", "DELETE_IN_PROGRESS"] | None = None,
        sort: Literal["ASC", "DESC"] = "ASC",
    ) -> list[str]:
        paginator = self.client.get_paginator("list_task_definitions")
        arns = []
        kwargs = (dict() if status is None else dict(status=status))
        async for page in paginator.paginate(
                    familyPrefix=family_prefix,
                    sort=sort,
                    **kwargs
                ):
            arns.extend(page["taskDefinitionArns"])
        return arns

    async def list_task_family_revisions_async(self, task_family: str) -> list[int]:
        arns = await self.list_task_definition_arns_async(family_prefix=task_family)  # ex: 'arn:aws:ecs:us-east-1:<aws_account_id>:task-definition/wordpress:3'
        arns = [arn for arn in arns if arn.split("/")[-1].startswith(task_family+":")]  # filter on exact task family name
        return [int(arn.split(":")[-1]) for arn in arns]
