import os
import pathlib
import asyncio
import aioboto3
from urllib.parse import urlparse
from typing import Iterable, Callable, Optional, AsyncIterable
from botocore.exceptions import ClientError


class S3Exception(Exception):
    pass


class S3:

    def __init__(self, region: str | None = None):
        self.session = aioboto3.Session()
        if region is None:
            self._region = self.session._session.get_config_variable("region")
        else:
            self._region = region
        self._client = None
        self._resource = None

    async def open(self):
        self._client = await self.session.client("s3", region_name=self._region).__aenter__()
        self._resource = await self.session.resource("s3", region_name=self._region).__aenter__()

    async def close(self):
        await self._client.__aexit__(None, None, None)
        self._client = None
        await self._resource.__aexit__(None, None, None)
        self._resource = None

    async def __aenter__(self) -> "S3":
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

    @property
    def resource(self) -> object:
        if self._resource is None:
            self._raise_not_initialized()
        else:
            return self._resource

    async def create_bucket_async(self, bucket_name: str):
        """
        Create a bucket
        """
        try:
            await self.client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": self._region}
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceInUseException":
                raise S3Exception(f"Bucket '{bucket_name}' already exists")
            else:
                raise


    async def delete_bucket_async(self, bucket_name: str):
        """
        Delete an existing bucket
        """
        try:
            await self.client.delete_bucket(Bucket=bucket_name)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                raise S3Exception(f"Bucket '{bucket_name}' does not exist")
            else:
                raise


    async def bucket_exists_async(self, bucket_name: str) -> bool:
        """
        Returns whether a bucket of the given name exists
        """
        try:
            await self.client.head_bucket(Bucket=bucket_name)
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in ["404", "NoSuchBucket"]:
                return False
            else:
                raise
        return True


    async def object_exists_async(self, bucket_name: str, key: str|pathlib.Path) -> bool:
        """
        returns whether an object exists on as3 or not
        """
        try:
            obj = await self.resource.Object(bucket_name, key)
            await obj.load()
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return False
            else:
                raise e
        return True


    async def get_object_bytes_size_async(self, bucket_name: str, key: str) -> int | None:
        """
        Return the bytes size of the object at given key, or None if it does not exists
        """
        try:
            response = await self.client.head_object(Bucket=bucket_name, Key=key)
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            else:
                raise
        return response["ContentLength"]


    async def list_objects_key_and_size_paginated_async(
            self,
            bucket_name: str,
            prefix: str | pathlib.Path="",
            recursive: bool=True,
            page_start_token: str | None = None,
            max_page_size: int = 100,
        ) -> tuple[list[tuple[str, int]], str | None]:
        """
        Return objects key and bytes size in a paginated fashion
        """
        if isinstance(prefix, pathlib.Path):
            prefix = prefix.as_posix()
        paginator = self.client.get_paginator("list_objects_v2")
        pagination_config = {"PageSize": max_page_size}
        if page_start_token:
            pagination_config["StartingToken"] = page_start_token
        kwargs = dict(
            Bucket=bucket_name,
            Prefix=prefix,
            PaginationConfig=pagination_config,
        )
        if not recursive:
            kwargs["Delimiter"] = "/"
        async for page in paginator.paginate(**kwargs):
            objects = [
                (obj["Key"], obj["Size"])
                for obj in page.get("Contents", [])
            ]
            return objects, page.get("NextContinuationToken")


    async def list_objects_key_and_size_async(self, bucket_name: str, prefix: str | pathlib.Path="") -> AsyncIterable[tuple[str, int]]:
        """
        Yield object keys and bytes size in a bucket at a prefix
        """
        next_page_token = None
        while True:
            page, next_page_token = await self.list_objects_key_and_size_paginated_async(bucket_name, prefix)
            for key, size in page:
                yield key, size
            if next_page_token is None:
                return


    async def upload_files_async(
            self,
            files_path: str | pathlib.Path,
            bucket_name: str,
            prefix: str | pathlib.Path,
            overwrite: bool = False,
            callback: Callable | None = None
        ):
        """
        upload the files in the given file path (or a single file path) to the given s3 bucket at given prefix
        """
        bucket = await self.resource.Bucket(bucket_name)
        files_path = pathlib.Path(files_path)
        prefix = pathlib.Path(prefix)
        if not files_path.exists():
            raise FileNotFoundError(f"The file_path '{files_path}' does not exist")
        iterable = os.walk(files_path) if files_path.is_dir() else [(files_path.parent, [], [file_path.name])]
        for root, dirs, files in iterable:
            root = pathlib.Path(root)
            for file in files:
                file_path = (root / file).as_posix()
                object_key = (prefix / root.relative_to(files_path) / file).as_posix()
                if not overwrite and await self.object_exists_async(bucket_name, object_key):
                    raise FileExistsError(f"An object with key '{object_key}' exist already, use overwrite=True to overwrite")
                await bucket.upload_file(file_path, object_key)
                if callback is not None:
                    callback(file_path=file_path, object_key=object_key)


    async def download_files_async(
            self,
            bucket_name: str,
            prefix: str | pathlib.Path,
            directory: str | pathlib.Path,
            create_missing_path: bool=False,
            callback: Callable | None = None
        ):
        """
        download the files at the given prefix (or a single file) of a given bucket in the given directory
        """
        bucket = await self.resource.Bucket(bucket_name)
        directory = pathlib.Path(directory)
        if not directory.exists():
            if create_missing_path:
                directory.mkdir(parents=True)
            else:
                raise NotADirectoryError(f"The directory '{directory}' does not exist, set create_missing_path=True to allow creating it")
        if not directory.is_dir():
            raise NotADirectoryError(f"The provided directory path '{directory}' is a file")
        prefix = pathlib.Path(prefix)
        for key, size in self.list_objects_key_and_size_async(bucket_name, prefix):
            file_path = directory / pathlib.Path(key).relative_to(prefix)
            file_path.parent.mkdir(exist_ok=True, parents=True)
            file_path = file_path.as_posix()
            await bucket.download_file(key, file_path)
            if callback is not None:
                callback(object_key=key, file_path=file_path)


    async def get_presigned_url_async(
                self,
                bucket_name: str,
                key: str,
                expires_seconds: int=3600
            ) -> str:
        """
        Returns a pre-signed URL (valid for a limited duration)
        """
        return await self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket_name,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{key.split("/")[-1]}"',
            },
            ExpiresIn=expires_seconds,
        )


    async def upload_data_async(
            self,
            data: bytes,
            bucket_name: str,
            key: str|pathlib.Path,
            overwrite: bool = False
        ):
        """
        save the given bytes as an object
        """
        if isinstance(key, pathlib.Path):
            key = key.as_posix()
        if not overwrite and await self.object_exists_async(bucket_name, key):
            raise S3Exception(f"An object with key '{key}' exist already, use overwrite=True to overwrite")
        obj = await self.resource.Object(bucket_name, key)
        await obj.put(Key=key, Body=data)


    async def download_data_async(self, bucket_name: str, key: str | pathlib.Path) -> bytes | None:
        """
        load the data stored in the given bucket file
        """
        if isinstance(key, pathlib.Path):
            key = key.as_posix()
        obj = await self.resource.Object(bucket_name, key)
        try:
            response = await obj.get()
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            else:
                raise
        return await response["Body"].read()
    
    
    async def batch_download_data_async(self, bucket_name: str, keys: list[str | pathlib.Path], batch_size: int=5) -> list[bytes | None]:
        """
        download all the keys by batches of 'batch_size' requests at once
        """
        results = []
        for i in range(0, len(keys), batch_size):
            results.extend(await asyncio.gather(*[self.download_data_async(bucket_name, key) for key in keys[i:i+batch_size]]))
        return results


    async def stream_data_async(self, bucket_name: str, key: str | pathlib.Path, chunk_size: int = 8192) -> AsyncIterable[bytes]:
        """
        Stream the data stored in the given S3 bucket file as async chunks.
        """
        if isinstance(key, pathlib.Path):
            key = key.as_posix()
        obj = await self.resource.Object(bucket_name, key)
        try:
            response = await obj.get()
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return  # yields nothing if file does not exist
            else:
                raise
        body = response["Body"]
        async for chunk in body.iter_chunks(chunk_size=chunk_size):
            yield chunk


    async def delete_objects_async(self, bucket_name: str, prefix: str | pathlib.Path, callback: Callable | None = None):
        """
        Delete all objects that match the prefix
        """
        bucket = await self.resource.Bucket(bucket_name)
        objects = [obj async for obj, size in self.list_objects_key_and_size_async(bucket_name, prefix)]
        delete = [{"Key": key} for i, key in zip(range(1_000), objects)]
        if len(delete) == 0:
            return
        await bucket.delete_objects(Delete={"Objects": delete})
        if callback is not None:
            for obj in delete:
                callback(object_key=obj["Key"])


    async def copy_object_async(
        self,
        source_bucket: str,
        source_key: str,
        dest_bucket: str,
        dest_key: str
    ):
        """
        Copy an object within S3.
        """
        copy_source = {"Bucket": source_bucket, "Key": source_key}
        await self.client.copy_object(
            Bucket=dest_bucket,
            Key=dest_key,
            CopySource=copy_source
        )


    async def delete_object_async(
        self,
        bucket_name: str,
        key: str
    ):
        """
        Delete an object from S3.
        If the object did not exist, do nothing silently.
        """
        await self.client.delete_object(Bucket=bucket_name, Key=key)


    async def move_object_async(
        self,
        source_bucket: str,
        source_key: str,
        dest_bucket: str,
        dest_key: str
    ):
        """
        Move an object in S3 by copying and then deleting.
        """
        await self.copy_object_async(source_bucket, source_key, dest_bucket, dest_key)
        await self.delete_object_async(source_bucket, source_key)


    async def initiate_multipart_upload_async(self, bucket_name: str, key: str, content_type: str = 'application/octet-stream') -> str:
        response = await self.client.create_multipart_upload(
            Bucket=bucket_name,
            Key=key,
            ContentType=content_type
        )
        return response['UploadId']


    async def upload_part_async(self, bucket_name: str, key: str, multipart_upload_id: str, part_number: int, chunk: bytes) -> str:
        response = await self.client.upload_part(
            Bucket=bucket_name,
            Key=key,
            PartNumber=part_number,
            UploadId=multipart_upload_id,
            Body=chunk
        )
        return response["ETag"]


    async def complete_multipart_upload_async(self, bucket_name: str, key: str, multipart_upload_id: str, part_tags: list[str]):
        await self.client.complete_multipart_upload(
            Bucket=bucket_name,
            Key=key,
            UploadId=multipart_upload_id,
            MultipartUpload={
                'Parts': [{'ETag': e_tag, 'PartNumber': i} for i, e_tag in enumerate(part_tags, start=1)]
            }
        )


    async def abort_multipart_upload_async(self, bucket_name: str, key: str, multipart_upload_id: str):
        await self.client.abort_multipart_upload(
            Bucket=bucket_name,
            Key=key,
            UploadId=multipart_upload_id
        )


    async def generate_download_url_async(self, bucket_name: str, key: str, expiration: int = 3600) -> str:
        """
        Generate a download url, for the given s3 object, with the given validity
        """
        return await self.client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': key},
            ExpiresIn=expiration
        )


    @staticmethod
    def s3_uri_to_bucket_and_key(self, s3_uri: str) -> tuple[str, str]:
        """
        Splits an "s3://bucket-name/s3/path" uri into a ("bucket-name", "s3/path") tuple of str
        """
        parsed = urlparse(s3_uri)
        scheme, s3_bucket, s3_object_key = parsed.scheme, parsed.netloc, parsed.path
        assert scheme == "s3"
        return s3_bucket, s3_object_key.lstrip("/")
