import aioboto3
from operator import __and__
from datetime import datetime, UTC
from typing import Literal, AsyncIterable
from pydantic import Field
from aws_tools._snake_base_model import _SnakeBaseModel


CpuArchitecture = Literal["i386", "x86_64", "arm64", "x86_64_mac", "arm64_mac"]
InstanceState = Literal["pending", "running", "shutting-down", "terminated", "stopping", "stopped"]
InstanceLifecycle = Literal["spot", "scheduled", "capacity-block", "interruptible-capacity-reservation"]


class Ec2InstanceDescription(_SnakeBaseModel):
    """
    Simplified response schema of boto3's 'describe_instances'
    https://docs.aws.amazon.com/boto3/latest/reference/services/ec2/client/describe_instances.html
    """

    class Tag(_SnakeBaseModel):
        """
        """
        key: str
        value: str

    class State(_SnakeBaseModel):
        """
        State of an EC2 instance
        """
        code: int
        name: InstanceState

    class SecurityGroup(_SnakeBaseModel):
        """
        """
        group_id: str
        group_name: str
    
    class IamInstanceProfile(_SnakeBaseModel):
        """
        """
        arn: str
        id: str
    
    class BlockDeviceMapping(_SnakeBaseModel):
        """
        """

        class Ebs(_SnakeBaseModel):
            """
            """

            class Operator(_SnakeBaseModel):
                """
                """
                managed: bool
                principal: str
                hidden_by_default: bool

            attach_time: datetime
            delete_on_termination: bool
            status: Literal["attaching", "attached", "detaching", "detached"]
            volume_id: str
            associated_resource: str | None = None
            volume_owner_id: str | None = None
            operator: Operator | None = None
            ebs_card_index: int | None = None

        device_name: str
        ebs: Ebs

    instance_id: str
    instance_type: str = Field(description="The EC2 naming of the instance type", examples=["m5.xlarge"])
    instance_lifecycle: InstanceLifecycle | None = None
    state: State
    launch_time: datetime
    image_id: str
    vpc_id: str
    subnet_id: str
    security_groups: list[SecurityGroup]
    private_ip_address: str
    public_ip_address: str | None = None
    tags: list[Tag] = Field(default_factory=list)
    iam_instance_profile: IamInstanceProfile | None = None
    block_device_mappings: list[BlockDeviceMapping]
    architecture: CpuArchitecture


class Ec2InstanceType(_SnakeBaseModel):
    """
    Simplified response schema of boto3's 'describe_instance_types'
    https://docs.aws.amazon.com/boto3/latest/reference/services/ec2/client/describe_instance_types.html
    """

    class ProcessorInfo(_SnakeBaseModel):
        supported_architectures: list[CpuArchitecture]
        sustained_clock_speed_in_ghz: float | None = None
        manufacturer: str

    class VCpuInfo(_SnakeBaseModel):
        default_vcpus: int | float = Field(alias="DefaultVCpus")
        default_cores: int
        default_threads_per_core: int
        valid_cores: list[int] | None = None
        valid_threads_per_core: list[int] | None = None

    class MemoryInfo(_SnakeBaseModel):
        size_in_MiB: int = Field(alias="SizeInMiB")
    
    class InstanceStorageInfo(_SnakeBaseModel):
        total_size_in_GiB: int = Field(alias="TotalSizeInGB")

    class NetworkInfo(_SnakeBaseModel):

        class EfaInfo(_SnakeBaseModel):
            maximum_efa_interfaces: int

        ipv4_addresses_per_interface: int
        ipv6_addresses_per_interface: int
        ipv6_supported: bool
        ena_support: Literal["unsupported", "supported", "required"]
        efa_supported: bool
        efa_info: EfaInfo | None = None
        secondary_network_supported: bool = False
        maximum_secondary_network_interfaces: int = 0
        ipv4_addresses_per_secondary_interface: int = 0

    class GpuInfo(_SnakeBaseModel):

        class Gpu(_SnakeBaseModel):
            name: str
            manufacturer: str
            count: int
            memory_info: "Ec2InstanceType.MemoryInfo"
            logical_gpu_count: int | None = None
            gpu_partition_size: float | None = None
            workloads: list[str] | None = None

        gpus: list[Gpu]
        total_gpu_memory_in_MiB: int = Field(alias="TotalGpuMemoryInMiB")

    instance_type: str = Field(description="The EC2 naming of the instance type", examples=["m5.xlarge"])
    current_generation: bool
    free_tier_eligible: bool
    supported_usage_classes: list[Literal["spot", "on-demand", "capacity-block"]]
    bare_metal: bool
    processor_info: ProcessorInfo
    vcpu_info: VCpuInfo = Field(alias="VCpuInfo")
    memory_info: MemoryInfo
    instance_storage_supported: bool
    network_info: NetworkInfo
    gpu_info: GpuInfo | None = None


class EC2:
    """
    An EC2 client that initalizes ec2 resources
    >>> ec2 = EC2()
    >>> await ec2.open()
    >>> ...
    >>> await ec2.close()

    It can also be used as an async context
    >>> async with EC2() as ec2:
    >>>     ...
    """

    def __init__(self, region_name: str | None = None):
        self.session = aioboto3.Session(region_name=region_name)
        self._client = None

    async def open(self):
        self._client = await self.session.client("ec2").__aenter__()

    async def close(self):
        await self.client.__aexit__(None, None, None)
        self._client = None

    async def __aenter__(self) -> "EC2":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    @property
    def client(self) -> object:
        if self._client is None:
            self._raise_not_initialized()
        else:
            return self._client

    def _raise_not_initialized(self):
        raise RuntimeError(f"{type(self).__name__} object was not awaited on creation, and as such, is not initialized")

    async def list_instance_types_paginated_async(
            self,
            page_start_token: str | None,
            prefixes_filter: list[str] | None = None,
            max_page_size: int | None = 100,
            instance_types: list[str] | None = None,
        ) -> tuple[list[Ec2InstanceType], str | None]:
        """
        Returns EC2 instance types in a paginated fashion as tuples of (page, next_page_token)
        """
        kwargs = dict()
        if instance_types is not None:
            kwargs["InstanceTypes"] = instance_types
        if prefixes_filter is not None:
            assert not isinstance(prefixes_filter, str)
            kwargs.setdefault("Filters", []).append(
                {
                    "Name": "instance-type",
                    "Values": [f"{prefix}*" for prefix in prefixes_filter]
                }
            )
        if page_start_token is not None:
            kwargs["NextToken"] = page_start_token
        if max_page_size is not None:
            kwargs["MaxResults"] = max_page_size
        response = await self.client.describe_instance_types(
            **kwargs
        )
        return [Ec2InstanceType(**it) for it in response["InstanceTypes"]], response.get("NextToken")

    async def list_instance_types_async(self, prefixes_filter: list[str] | None = None) -> AsyncIterable[Ec2InstanceType]:
        """
        Return an async iterable over the ec2 instance types
        """
        next_page_token = None
        while True:
            page, next_page_token = await self.list_instance_types_paginated_async(next_page_token, prefixes_filter=prefixes_filter)
            for it in page:
                yield it
            if next_page_token is None:
                break

    async def get_instance_type_properties_async(self, instance_type: str) -> Ec2InstanceType | None:
        """
        Get the properties of an instance type, or return None if not found
        """
        page, _ = await self.list_instance_types_paginated_async(page_start_token=None, max_page_size=None, instance_types=[instance_type])
        return page[0]

    async def run_instances_async(
            self,
            instance_type: str,
            image_id: str,
            subnet_id: str,
            security_group_ids: list[str],
            iam_instance_profile_arn: str | None,
            count: int = 1,
            public_ip: bool = False,
            tags: dict[str, str] | None = None,
            disk_size_GiB: int | None = None,
            user_data_script: str | None = None,
            ssh_key_name: str | None = None,
            one_thread_per_core: bool = False,
            instance_initiated_shutdown_behaviour: Literal["stop", "terminate"] = "terminate",
        ) -> list[str]:
        """
        Initialize one or several instance, return their IDs
        """
        assert len(security_group_ids) > 0
        kwargs = dict()
        if ssh_key_name is not None:
            kwargs["KeyName"] = ssh_key_name
        if disk_size_GiB is not None:
            kwargs["BlockDeviceMappings"] = [
                {
                    "DeviceName": "/dev/xvda",
                    "Ebs": {
                        "VolumeSize": disk_size_GiB,
                        "DeleteOnTermination": True,
                        "VolumeType": "gp3",
                    },
                }
            ]
        if user_data_script is not None:
            kwargs["UserData"] = user_data_script
        if one_thread_per_core:
            kwargs["CpuOptions"] = {
                "CoreCount": (await self.get_instance_type_properties_async(instance_type)).vcpu_info.default_cores,
                "ThreadsPerCore": 1
            }
        if iam_instance_profile_arn is not None:
            kwargs["IamInstanceProfile"] = {
                "Arn": iam_instance_profile_arn,
            }
        if tags is not None:
            kwargs["TagSpecifications"] = {
                "ResourceType": "instance",
                "Tags": [
                    {
                        "Key": k,
                        "Value": v
                    }
                    for k, v in tags.items()
                ]
            }
        response = await self.client.run_instances(
            ImageId=image_id,
            InstanceType=instance_type,
            MinCount=count,
            MaxCount=count,
            NetworkInterfaces=[
                {
                    "AssociatePublicIpAddress": public_ip,
                    "DeviceIndex": 0,
                    "SubnetId": subnet_id,
                    "Groups": security_group_ids,
                }
            ],
            InstanceInitiatedShutdownBehavior=instance_initiated_shutdown_behaviour,
            **kwargs
        )
        return [inst["InstanceId"] for inst in response["Instances"]]

    async def list_instances_paginated_async(
            self,
            page_start_token: str | None,
            instance_state_filter: None | list[InstanceState] = None,
            max_page_size: int | None = 100,
            instance_ids: list[str] | None = None,
        ) -> tuple[list[Ec2InstanceDescription], str | None]:
        """
        Returns (page, next_page_token) with page a list of running instances
        """
        kwargs = dict()
        if page_start_token is not None:
            kwargs["NextToken"] = page_start_token
        if instance_state_filter is not None:
            kwargs.setdefault("Filters", list()).append(
                {
                    "Name": "instance-state-name",
                    "Values": instance_state_filter,
                }
            )
        if instance_ids is not None:
            kwargs["InstanceIds"] =  instance_ids
        if max_page_size is not None:
            kwargs["MaxResults"] = max_page_size
        response = await self.client.describe_instances(
            **kwargs
        )
        page = [
            Ec2InstanceDescription(**instance)
            for reservation in response["Reservations"]
            for instance in reservation["Instances"]
        ]
        return page, response.get("NextToken")

    async def list_instances_async(
            self,
            instance_state_filter: None | list[InstanceState] = None
    ) -> AsyncIterable[Ec2InstanceDescription]:
        """
        Yield instances in an async fashion
        """
        next_page_token = None
        while True:
            page, next_page_token = await self.list_instances_paginated_async(next_page_token, instance_state_filter)
            for description in page:
                yield description
            if next_page_token is None:
                break

    async def get_instance_async(self, instance_id: str) -> Ec2InstanceDescription | None:
        """
        Describe an existing instance, or return None if it does not exists
        """
        page, _ = await self.list_instances_paginated_async(page_start_token=None, max_page_size=None, instance_ids=[instance_id])
        return page[0]

    async def stop_instances_async(self, instance_ids: list[str]):
        """
        Initiate the instance shutdown
        """
        await self.client.stop_instances(
            InstanceIds=instance_ids
        )

    async def stop_instance_async(self, instance_id: str):
        """
        Initiate the instance shutdown
        """
        await self.stop_instances_async([instance_id])
