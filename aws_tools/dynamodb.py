import json
import aioboto3
from operator import __and__
from datetime import datetime
from base64 import urlsafe_b64encode, urlsafe_b64decode
from typing import Literal, Iterable, AsyncIterable, Generator, Awaitable, Any
from collections.abc import Iterable as IterableABC, AsyncIterable as AsyncIterableABC
from decimal import Decimal
from boto3.dynamodb.types import TypeSerializer, TypeDeserializer
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError


KeyType = dict[Literal["HASH", "RANGE"], object]


def _recursive_convert(item: object, to_decimal: bool, n_decimals: int=9) -> object:
        """
        convert floats to Decimals (or inversely) recursively in a JSON serialisable
        """
        if isinstance(item, list):
            return [_recursive_convert(i, to_decimal) for i in item]
        elif isinstance(item, set):
            return {_recursive_convert(i, to_decimal) for i in item}
        elif isinstance(item, datetime):
            return item.isoformat()
        elif isinstance(item, dict):
            return {k: _recursive_convert(v, to_decimal) for k, v in item.items() if v != set()}  # remove keys corresponding to empty sets
        elif item is None or isinstance(item, (str, bool)):
            return item
        elif isinstance(item, (int, float)) and to_decimal:
            number = str(round(item, n_decimals))
            if "." in number:
                int_part, decimal_part = number.split(".")
                number = f"{int_part}.{decimal_part[:n_decimals]}"
            return Decimal(number)
        elif isinstance(item, Decimal) and not to_decimal:
            return float(item) if item % 1 != 0 else int(item)
        else:
            raise ValueError(f"Unexpected type '{type(item).__name__}' encountered.")


class Conditions:
    """
    Base class representing a node in the Conditions tree.
    """

    def __init__(self, operator: str, operands: list["Conditions", "Attr", Any]):
        self.operator = operator
        self.operands = operands

    def __and__(self, other: "Conditions") -> "Conditions":
        return Conditions('AND', [self, other])

    def __or__(self, other: "Conditions") -> "Conditions":
        return Conditions('OR', [self, other])

    def __invert__(self) -> "Conditions":
        return Conditions('NOT', [self])

    def attribute_names(self) -> Iterable[str]:
        """
        yield all the attributes in the condition recursively
        """
        for leaf in self.operands:
            if isinstance(leaf, Conditions):
                yield from leaf.attribute_names()
            elif isinstance(leaf, Attr):
                if isinstance(leaf.field_path, str):
                    yield leaf.field_path
                else:
                    yield from (p for p in leaf.field_path if isinstance(p, str))

    def _format_operation(self, operator: str, operands: list[str]) -> str:
        """
        Convert to a string operation
        """
        if operator.endswith("()"):
            return f"{operator.removesuffix('()')}({', '.join(operands)})"
        elif len(operands) == 1:
            return f"({operator} {operands[0]})"
        elif len(operands) == 2:
            return f"({operands[0]} {operator} {operands[1]})"
        else:
            raise ValueError(f"Unexpected operands count '{len(operands)}'")

    def _register_value(self, attribute_value: Any, attribute_values: dict[str, Any]) -> str:
        """
        Register a condition value in the mapping an return it's reference
        """
        attribute_name = f":condition{sum(v.startswith(":condition") for v in attribute_values)}"
        attribute_values[attribute_name] = _recursive_convert(attribute_value, to_decimal=True)
        return attribute_name

    def condition_expression(self, inverse_attribute_names: dict[str, str], attribute_values: dict[str, Any]) -> str:
        """
        Returns the condition_expression corresponding to the given condition
        """
        operand_strings = [
            o.condition_expression(inverse_attribute_names, attribute_values) if isinstance(o, Conditions)
            else o.field_alias(inverse_attribute_names) if isinstance(o, Attr)
            else self._register_value(o, attribute_values)
            for o in self.operands
        ]
        return self._format_operation(self.operator, operand_strings)


class Attr:
    """
    The entry point for building query/scan/update conditions
    """
    
    def __init__(self, field_path: str | tuple[str | int]):
        self.field_path = field_path

    def field_alias(self, inverse_attribute_names: dict[str, str]) -> str:
        """
        """
        if isinstance(self.field_path, str):
            return inverse_attribute_names[self.field_path]
        else:
            return inverse_attribute_names[self.field_path[0]] + "".join(f"[{f}]" if isinstance(f, int) else "."+inverse_attribute_names[f] for f in self.field_path[1:])

    def eq(self, value: Any) -> Conditions:
        return Conditions('=', [self, value])

    def ne(self, value: Any) -> Conditions:
        return Conditions('<>', [self, value])

    def lt(self, value: Any) -> Conditions:
        return Conditions('<', [self, value])

    def lte(self, value: Any) -> Conditions:
        return Conditions('<=', [self, value])

    def gt(self, value: Any) -> Conditions:
        return Conditions('>', [self, value])

    def gte(self, value: Any) -> Conditions:
        return Conditions('>=', [self, value])

    def begins_with(self, value: Any) -> Conditions:
        return Conditions('begins_with()', [self, value])

    def contains(self, value: Any) -> Conditions:
        return Conditions('contains()', [self, value])

    def exists(self) -> Conditions:
        return Conditions('attribute_exists()', [self])

    def not_exists(self) -> Conditions:
        return Conditions('attribute_not_exists()', [self])


class DynamoDBException(Exception):
    """
    An exception for DynamoDB errors
    """
    pass


class DynamoDB:
    """
    A dynamodb connector that initalizes dynamodb resources
    >>> ddb = DynamoDB()
    >>> await ddb.open()
    >>> ...
    >>> await ddb.close()

    It can also be used as an async context
    >>> async with DynamoDB() as ddb:
    >>>     ...
    """

    def __init__(self):
        self.session = aioboto3.Session()
        self._resource = None
        self._client = None

    async def open(self):
        self._resource = await self.session.resource("dynamodb").__aenter__()
        self._client = await self.session.client("dynamodb").__aenter__()

    async def close(self):
        await self.resource.__aexit__(None, None, None)
        self._resource = None
        await self.client.__aexit__(None, None, None)
        self._client = None

    async def __aenter__(self) -> "DynamoDB":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def _raise_not_initialized(self):
        raise RuntimeError(f"{type(self).__name__} object was not awaited on creation, and as such, is not initialized")

    @property
    def resource(self) -> object:
        if self._resource is None:
            self._raise_not_initialized()
        else:
            return self._resource

    @property
    def client(self) -> object:
        if self._client is None:
            self._raise_not_initialized()
        else:
            return self._client


    async def create_table_async(
            self,
            table_name: str,
            partition_names: dict[Literal["HASH", "RANGE"], str],
            data_types: dict[str, Literal["S", "N", "B"]],
            ttl_attribute: str | None = None,
        ):
        """
        Creates a table, raise an error if it already exists.

        Example
        -------
        >>> table = create_table("test-table")
        """
        try:
            table = await self.resource.create_table(
                TableName=table_name,
                KeySchema=[
                    {
                        'AttributeName': partition_name,
                        'KeyType': partition_type
                    }
                for partition_type, partition_name in partition_names.items()],
                AttributeDefinitions=[
                    {
                        'AttributeName': name,
                        'AttributeType': data_type
                    }
                for name, data_type in data_types.items()],
                BillingMode='PAY_PER_REQUEST'
            )
            # Wait until the table exists before continuing
            await table.meta.client.get_waiter('table_exists').wait(TableName=table_name)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceInUseException":
                raise DynamoDBException(f"The table '{table_name}' already exists")
            else:
                raise
        if ttl_attribute:
            try:
                await self.resource.update_time_to_live(
                    TableName=table_name,
                    TimeToLiveSpecification={
                        "Enabled": True,
                        "AttributeName": ttl_attribute
                    }
                )
            except ClientError as e:
                raise RuntimeError(f"Failed to enable TTL: {e}")


    async def delete_table_async(self, table_name: str, blocking: bool=True):
        """
        Delete a table, raise an error if it does not exists

        Example
        -------
        >>> table = delete_table("test_table")
        """
        con = await Table(self, table_name)
        try:
            await con.table.delete()
            # Wait until the table is correctly deleted before continuing
            if blocking:
                await con.table.meta.client.get_waiter('table_not_exists').wait(TableName=con.name)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                raise DynamoDBException(f"The table '{con.name}' does not exist")
            else:
                raise


    async def list_table_names_async(self) -> list[str]:
        """
        list existing tables
        """
        return [table.name async for table in self.resource.tables.all()]


    async def table_exists_async(self, table_name: str) -> bool:
        """
        Returns True if the table exists and False otherwise
        """
        try:
            table = await Table(self, table_name)
        except DynamoDBException:
            return False
        else:
            return True


class Table(Awaitable["Table"]):
    """
    >>> async with DynamoDBConnector as ddb:
    >>>     table = await Table(ddb, "test-table")
    """

    def __init__(self, ddb: DynamoDB, name: str):
        self.name = name
        self._ddb = ddb
        self._ddb_table = None
        self._keys = None

    def __await__(self) -> Generator[Any, None, "Table"]:
        return self._inititialize().__await__()

    async def _inititialize(self) -> "Table":
        self._ddb_table = await self._ddb.resource.Table(self.name)
        try:
            await self._ddb_table.load()
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                raise DynamoDBException(f"The table '{self.name}' does not exist")
            else:
                raise
        self._keys = {ks["KeyType"]: ks["AttributeName"] for ks in await self._ddb_table.key_schema}
        return self

    def _raise_not_initialized(self):
        raise RuntimeError(f"Table '{self.name}' was not awaited after creation, it is not properly intialized")

    @staticmethod
    def _extract_item_field_value(item: dict | None, field_path: str | tuple[str | int]) -> object:
        """
        returns the value at given path

        Example
        -------
        >>> _extract_item_field_value({"array": ["A", "B", {"sub_field": 1}]}, ["array", 2, "sub_field"])
        1
        """
        if isinstance(field_path, str):
            field_path = (field_path,)
        for key in field_path:
            item = item[key]
        return item

    @staticmethod
    def _field_exists(item: dict | None, field_path: str | tuple[str | int]) -> bool:
        """
        returns whether a field path exists within an item

        Example
        -------
        >>> _field_exists({"array": ["A", "B", {"sub_field": 1}]}, ["array", 2, "sub_field"])
        True
        >>> _fields_exists({"array": ["A", "B", {"sub_field": 1}]}, ["array", 2, "other_sub_field"])
        False
        >>> _field_exists({"array": ["A", "B", {"sub_field": 1}]}, "array")
        True
        >>> _field_exists({"array": ["A", "B", {"sub_field": 1}]}, "other_field")
        False
        """
        if isinstance(field_path, str):
            field_path = (field_path,)
        for key in field_path:
            if isinstance(key, str) and key not in item:
                return False
            elif isinstance(key, int) and (not isinstance(item, list) or key >= len(item)):
                return False
            item = item[key]
        return True

    @staticmethod
    def _field_path_to_expression(*args: tuple[str | tuple[str | int], ...]) -> tuple[tuple[str, ...], dict[str, str]]:
        """
        converts a set of field path to a tuple of (expressions, path_representation, attribute_names)

        Example
        -------
        >>> _field_path_to_expression(("array_field", 0, "sub_field"), ("array_field", 1, "other_subfield"))
        (('#f2[0].#f0', '#f2[1].#f1'),
        {'#f0': 'sub_field', '#f1': 'other_subfield', '#f2': 'array_field'})
        """
        args = tuple((f,) if isinstance(f, str) else f for f in args)
        unique_attributes = {f for arg in args for f in arg if isinstance(f, str)}
        attributes_mapping = {k: f"#f{i}" for i, k in enumerate(unique_attributes)}
        expressions = tuple("".join("."+attributes_mapping[f] if isinstance(f, str) else f"[{f}]" for f in arg).strip(".") for arg in args)
        attribute_names = {v: k for k, v in attributes_mapping.items()}
        return expressions, attribute_names

    def _key_exists_condition(self) -> Conditions:
        """
        Return the condition that the key exists
        """
        conditions = Attr(self.keys["HASH"]).exists()
        if "RANGE" in self.keys.keys():
            conditions = conditions & Attr(self.keys["RANGE"]).exists()
        return conditions

    def _key_not_exists_condition(self) -> Conditions:
        """
        Return the condition that the key does not exist
        """
        conditions = Attr(self.keys['HASH']).not_exists()
        if "RANGE" in self.keys.keys():
            conditions = conditions | Attr(self.keys["RANGE"]).not_exists()
        return conditions

    @property
    def table(self) -> object:
        if self._ddb_table is None:
            self._raise_not_initialized()
        else:
            return self._ddb_table
    
    @property
    def keys(self) -> KeyType:
        if self._keys is None:
            self._raise_not_initialized()
        else:
            return self._keys

    async def item_exists_async(self, key_or_item: dict, consistent_read: bool=False) -> bool:
        """
        Returns True if the item exists and False otherwise.
        For big objects, this is faster than a 'get_item', as this only query the partition key.
        """
        key = {v: key_or_item[v] for v in self.keys.values()}
        response = await self.table.get_item(
            Key=key,
            ProjectionExpression=",".join(key.keys()),
            ConsistentRead=consistent_read
        )
        return "Item" in response

    async def get_item_async(self, key_or_item: dict, consistent_read: bool=False) -> dict | None:
        """
        Get a full item from it's keys, returns None if the key does not exist.
        If the table has an hash key and a range key, both must be provided in the 'keys' dict.

        Example
        -------
        >>> get_item(table, {"id": "ID0"})
        {"uuid": "ID0", "field": 10.0}
        """
        response = await self.table.get_item(
            Key={v: key_or_item[v] for v in self.keys.values()},
            ConsistentRead=consistent_read
        )
        return _recursive_convert(response.get("Item"), to_decimal=False)

    async def put_item_async(self, item: dict, overwrite: bool=False, return_object: bool=False) -> dict | None:
        """
        Write an item, raise an error if it already exists and overwrite=False.
        Returns the old value if return_object=True.

        Example
        -------
        >>> put_item(table, {"uuid": "ID0", "field": 10.0})
        >>> put_item(table, {"uuid": "ID0", "field": 9.0}, overwrite=True, return_object=True)
        {"uuid": "ID0", "field": 10.0}
        """
        conditions = self._key_not_exists_condition() if not overwrite else None
        _, attribute_names = self._field_path_to_expression(*(v for v in self.keys.values()))
        assert all(k in item.keys() for k in self.keys.values())
        if conditions is not None:
            attribute_values = dict()
            condition_expression = conditions.condition_expression({v: k for k, v in attribute_names.items()}, attribute_values)
        else:
            attribute_values = None
            condition_expression = None
        try:
            response = await self.table.put_item(
                Item=_recursive_convert(item, to_decimal=True),
                ReturnValues="ALL_OLD" if return_object else "NONE",  # returns the overwritten item if any
                **(dict() if conditions is None else dict(
                    ConditionExpression=condition_expression,
                    ExpressionAttributeNames=attribute_names
                )),
                **(dict() if attribute_values is None or len(attribute_values) == 0 else dict(
                    ExpressionAttributeValues=attribute_values
                )),
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                key = {k: item[k] for k in self.keys.values()}
                raise DynamoDBException(f"Item '{key}' already exists for table '{self.table.name}'")
            else:
                raise
        return _recursive_convert(response.get("Attributes"), to_decimal=False)

    async def batch_get_items_async(self, keys_or_items: Iterable[dict], chunk_size: int=100, consistent_read: bool=False) -> AsyncIterable[dict | None]:
        """
        Get several items at once.
        Yield None for items that do not exist.
        """
        if chunk_size > 100:
            raise ValueError(f"Argument 'chunk_size' must not be greater than 100 as per dynamodb limitation. got {chunk_size}.")
        serializer = TypeSerializer()
        deserializer = TypeDeserializer()
        keys_to_process = ({k: item[k] for k in self.keys.values()} for item in keys_or_items)
        while True:
            chunk_keys = [key for _, key in zip(range(chunk_size), keys_to_process)]
            if len(chunk_keys) == 0:
                break
            processed_items = {}
            unprocessed_keys = [{k: serializer.serialize(v) for k, v in key.items()} for key in chunk_keys]
            while len(unprocessed_keys) > 0:
                response = await self._ddb.client.batch_get_item(RequestItems={self.name: {"Keys": unprocessed_keys, "ConsistentRead": consistent_read}})
                processed_items.update(
                    {
                        tuple(deserializer.deserialize(item[k]) for k in self.keys.values()) : {kk: deserializer.deserialize(vv) for kk, vv in item.items()}
                        for item in response["Responses"].get(self.name, [])
                    }
                )
                unprocessed_keys = response.get("UnprocessedKeys", {}).get(self.name, {}).get("Keys", [])
            for key in chunk_keys:
                yield _recursive_convert(processed_items.get(tuple(key[k] for k in self.keys.values())), to_decimal=False)

    async def batch_put_items_async(self, items: Iterable[dict] | AsyncIterable[dict]):
        """
        Create items in batch, overwriting if they already exist.
        """
        async with self.table.batch_writer() as batch:
            if isinstance(items, AsyncIterableABC):
                async for item in items:
                    await batch.put_item(Item=_recursive_convert(item, to_decimal=True))
            elif isinstance(items, IterableABC):
                for item in items:
                    await batch.put_item(Item=_recursive_convert(item, to_decimal=True))
            else:
                raise ValueError("Expected iterable for argument 'items'")

    async def delete_item_async(self, key_or_item: dict, return_object: bool = False) -> dict | None:
        """
        Delete an item at given key, and optionally return the erased item.
        Does not fail if the item does not exists.
        Returns None instead if the item did not exists.

        Example
        -------
        >>> delete_item(table, {"id": "ID0"})
        >>> delete_item(table, {"id": "ID0"}, return_object=True)
        {"uuid": "ID1", "field": 10.0}
        """
        conditions = self._key_exists_condition()
        _, attribute_names = self._field_path_to_expression(*conditions.attribute_names())
        attribute_values = dict()
        condition_expression = conditions.condition_expression({v: k for k, v in attribute_names.items()}, attribute_values)
        try:
            response = await self.table.delete_item(
                Key={k: key_or_item[k] for k in self.keys.values()},
                ReturnValues="ALL_OLD" if return_object else "NONE",  # returns the removed item
                ConditionExpression=condition_expression,
                ExpressionAttributeNames=attribute_names,
                **(dict() if len(attribute_values) == 0 else dict(ExpressionAttributeValues=attribute_values)),
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            else:
                raise
        return _recursive_convert(response.get("Attributes"), to_decimal=False)

    async def batch_delete_items_async(self, keys_or_items: Iterable[dict] | AsyncIterable[dict]):
        """
        Delete the items by batch, there is no verification that they did not exist.
        """
        async with self.table.batch_writer() as batch:
            if isinstance(keys_or_items, AsyncIterableABC):
                async for key in keys_or_items:
                    await batch.delete_item(Key={v: key[v] for v in self.keys.values()})
            elif isinstance(keys_or_items, IterableABC):
                for key in keys_or_items:
                    await batch.delete_item(Key={v: key[v] for v in self.keys.values()})
            else:
                raise ValueError("Expected iterable for 'keys_or_items' argument")

    async def scan_items_paginated_async(
            self,
            conditions: Conditions | None = None,
            subset: list[str] | None = None,
            page_size: int | None = 100,
            page_start_token: str | None = None,
            consistent_read: bool=False,
        ) -> tuple[list[dict], str | None]:
        """
        Scan all items in the table.
        Return items in a paginated way.

        Params
        ------
        table : object
            The dynamodb Table object
        conditions : Conditions
            the conditions on which returned items are filtered
        subset : list of str or None
            the subset of fields to return, when fields are not all usefull, to avoid returning the full object
            (dynamoDB is billed by the byte)
        page_size : int or None
            Maximum number of items returned in a single page.
            The number of items per page might be less than that if some filters ('conditions' argument) are applied.
        next_page_token : str or None
            If None, start the query from the beginning.
            If provided, resume the query from the last page.
            Must be a token returned by a call of this function on the same table,
            with the same parameters.

        Returns
        -------
        tuple :
            the (results, next_page_token) tuple, where results is a list of dict items,
            and 'next_page_token' must be passed as 'page_start_token' argument in the next call to resume the query (if it is not None).

        Example
        -------
        >>> from boto3.dynamodb.conditions import Attr
        >>> put_item(table, {"uuid": "ID0", "field": 10.0})
        >>> next_page_token = None
        >>> while True:
        >>>     items, next_page_token = scan_items(table, conditions=Attr("field").eq(10.0), page_start_token=next_page_token):
        >>>     print(item)
        {"uuid": "ID0", "field": 10.0}
        """
        if conditions is not None:
            _, attribute_names = self._field_path_to_expression(*conditions.attribute_names())
            attribute_values = dict()
            filter_expression = conditions.condition_expression({v: k for k, v in attribute_names.items()}, attribute_values)
        else:
            attribute_names = None
            attribute_values = None
            filter_expression = None
        kwargs = {
            **(dict(FilterExpression=filter_expression) if filter_expression is not None else dict()),
            **(dict(ExpressionAttributeNames=attribute_names) if attribute_names is not None else dict()),
            **(dict(ExpressionAttributeValues=attribute_values) if attribute_values is not None  and len(attribute_values) > 0 else dict()),
            **(dict(ExclusiveStartKey=json.loads(urlsafe_b64decode(page_start_token.encode()).decode())) if page_start_token is not None else dict()),
            **(dict(ProjectionExpression=",".join(subset)) if subset is not None else dict()),
            **(dict(Limit=page_size) if page_size is not None else dict())
        }
        response = await self.table.scan(ConsistentRead=consistent_read, **kwargs)
        last_key = response.get("LastEvaluatedKey") or {}
        next_page_token = urlsafe_b64encode(json.dumps(last_key).encode()).decode() if len(last_key) > 0 else None
        return ([_recursive_convert(item, to_decimal=False) for item in response.get("Items", [])], next_page_token)

    async def scan_all_items_async(
                self,
                conditions: Conditions | None = None,
                subset: list[str] | None = None,
                page_size: int | None = 100,
                consistent_read: bool=False,
            ) -> AsyncIterable[dict]:
        """
        Return all the items returned by a scan operation, handling pagination
        """
        kwargs = dict(
            conditions=conditions,
            subset=subset,
            page_size=page_size,
            consistent_read=consistent_read,
        )
        next_page_token = None
        while True:
            items, next_page_token = await self.scan_items_paginated_async(page_start_token=next_page_token, **kwargs)
            for item in items:
                yield item
            if next_page_token is None:
                break

    async def query_items_paginated_async(
            self,
            hash_key: object,
            page_start_token: str | None,
            sort_key_filter: str | tuple[object|None, object|None] = (None, None),
            ascending: bool=True,
            conditions: Conditions | None = None,
            subset: list[str] | None = None,
            page_size: int | None = 100,
            consistent_read: bool=False,
        ) -> tuple[list[dict], str | None]:
        """
        Query items that match the hash key and/or the sort key.
        Return items in a paginated way.

        Params
        ------
        table : object
            The dynamodb Table object
        hash_key : object
            the value of the hash_key for returned items
        sort_key_filter : str, or tuple of two objects, or None
            Ignored if the table does not have a sort key.
            If a single str is provided, query items for which sort key begin with the provided string.
            If a (from, to) tuple is provided, it is the interval (including boundary on both sides) used to filter the sort key, a None means an unbounded side for the interval
        ascending : bool
            If one of 'hash_key' or 'sort_key' is provided, the results are returned by ascending (or descending) order of 'sort_key'.
            Otherwise it has no effect, as the full scan is not ordered.
        conditions : Conditions
            the conditions on which returned items are filtered
        subset : list of str or None
            the subset of fields to return, when fields are not all usefull, to avoid returning the full object
            (dynamoDB is billed by the byte)
        page_size : int or None
            Maximum number of items returned in a single page.
            The number of items per page might be less than that if some filters ('conditions' argument) are applied.
        next_page_token : str or None
            If None, start the query from the beginning.
            If provided, resume the query from the last page.
            Must be a token returned by a call of this function on the same table,
            with the same parameters.

        Returns
        -------
        tuple :
            the (results, next_page_token) tuple, where results is a list of dict items,
            and 'next_page_token' must be passed as 'page_start_token' argument in the next call to resume the query (if it is not None).

        Example
        -------
        >>> from boto3.dynamodb.conditions import Attr
        >>> put_item(table, {"uuid": "ID0", "field": 10.0})
        >>> next_page_token = None
        >>> while True:
        >>>     items, next_page_token = query_items(table, hash_key="ID0", conditions=Attr("field").eq(10.0), page_start_token=next_page_token):
        >>>     print(item)
        {"uuid": "ID0", "field": 10.0}
        """
        key_conditions = Key(self.keys["HASH"]).eq(hash_key)
        if "RANGE" in self.keys.keys():
            sort_key = Key(self.keys["RANGE"])
            if isinstance(sort_key_filter, str):
                key_conditions = key_conditions & sort_key.begins_with(sort_key_filter)
            else:
                sort_key_start, sort_key_end = sort_key_filter
                if any(k is not None for k in sort_key_filter): # Only a single condition by key is supported by boto3
                    if (sort_key_start is not None) and (sort_key_end is not None):
                        key_conditions = key_conditions & sort_key.between(sort_key_start, sort_key_end)
                    elif sort_key_start is not None:
                        key_conditions = key_conditions & sort_key.gte(sort_key_start)
                    elif sort_key_end is not None:
                        key_conditions = key_conditions & sort_key.lte(sort_key_end)
        if conditions is not None:
            _, attribute_names = self._field_path_to_expression(*conditions.attribute_names())
            attribute_values = dict()
            filter_expression = conditions.condition_expression({v: k for k, v in attribute_names.items()}, attribute_values)
        else:
            attribute_names = None
            attribute_values = None
            filter_expression = None
        # get a single page of results
        kwargs = {
            **(dict(FilterExpression=filter_expression) if filter_expression is not None else dict()),
            **(dict(ExpressionAttributeNames=attribute_names) if attribute_names is not None else dict()),
            **(dict(ExpressionAttributeValues=attribute_values) if attribute_values is not None and len(attribute_values) > 0 else dict()),
            **(dict(ExclusiveStartKey=json.loads(urlsafe_b64decode(page_start_token.encode()).decode())) if page_start_token is not None else dict()),
            **(dict(ProjectionExpression=",".join(subset)) if subset is not None else dict()),
            **(dict(Limit=page_size) if page_size is not None else dict())
        }
        response = await self.table.query(
            KeyConditionExpression=key_conditions,
            ScanIndexForward=ascending,
            ConsistentRead=consistent_read,
            **kwargs
        )
        last_key = response.get("LastEvaluatedKey") or {}
        next_page_token = urlsafe_b64encode(json.dumps(last_key).encode()).decode() if len(last_key) > 0 else None
        return ([_recursive_convert(item, to_decimal=False) for item in response.get("Items", [])], next_page_token)

    async def query_all_items_async(
            self,
            hash_key: object,
            sort_key_filter: str | tuple[object|None, object|None] = (None, None),
            ascending: bool=True,
            conditions: Conditions | None = None,
            subset: list[str] | None = None,
            page_size: int | None = 100,
            consistent_read: bool = False,
        ) -> AsyncIterable[dict]:
        """
        Iterate over all the results of a query, handling pagination
        """
        kwargs = dict(
            hash_key=hash_key,
            sort_key_filter=sort_key_filter,
            ascending=ascending,
            conditions=conditions,
            subset=subset,
            page_size=page_size,
            consistent_read=consistent_read,
        )
        next_page_token = None
        while True:
            items, next_page_token = await self.query_items_paginated_async(page_start_token=next_page_token, **kwargs)
            for item in items:
                yield item
            if next_page_token is None:
                break

    async def update_item_async(
            self,
            key_or_item: dict,
            *,
            put_fields: dict[str | tuple[str | int], object] = {},
            increment_fields: dict[str | tuple[str | int], object] = {},
            extend_sets: dict[str | tuple[str | int], object | set] = {},
            remove_from_sets: dict[str | tuple[str | int], object | set] = {},
            extend_arrays: dict[str | tuple[str | int], list] = {},
            delete_fields: set[str | tuple[str | int]] = set(),
            create_item_if_missing: bool=False,
            conditions: Conditions | None = None,
            return_object: Literal["OLD", "NEW", None]=None
        ) -> dict | None:
        """
        Update an item fields.
        Only one operation can be done on a single field at a time.
        A set of conditions can optionaly be specified, in which case the update only happen if they are met, and do nothing silently otherwise, and return None if 'return_object' is specified.
        The 'create_if_missing' is implemented as an additional condition, so if it is False, updating will silently do nothing.

        Params
        ------
        table : object
            The dynamodb Table object
        key_or_item : dict
            The item or the key of the item to update.
        put_fields : dict
            the field names or paths, and their associated values to set
        increment_fields : dict
            the field names or paths, and their associated values to increment (if the field is missing, set it to the increment value instead)
        extend_sets : dict
            the field names or paths, and the associated values to add to a set (if the field is missing, create it with the value)
        remove_from_sets : dict
            the field names or paths, and the associated values to remove from a set
        extend_arrays : dict
            the field names or paths, and the associated list of values to append to an array (if the field is missing, create it with the value)
        delete_fields : dict
            the field names or paths to delete from the item
        create_item_if_missing : bool
            If True, create the item if it does not exist.
            Several nested paths can't be created at once.
            If False, raise an error if the item does not exist.
        conditions : boto3.dynamodb.conditions.Conditions or None
            The conditions to be met. If the condition is not met, the function always returns None, even if return_object is not None.
        return_object : "OLD", "NEW" or None
            If not None, the function return the subset of the item containing the updated fields. (values before update if "OLD", values after update if "NEW")

        Returns
        -------
        dict | None
            The updated item if return_object is True, otherwise None.
        """
        if sum(len(v) for v in (put_fields, increment_fields, extend_sets, remove_from_sets, extend_arrays, delete_fields)) == 0:
            raise DynamoDBException("At least one update must be made to the item")
        if not create_item_if_missing:
            key_exists_condition = self._key_exists_condition()
            conditions = key_exists_condition if conditions is None else (conditions & key_exists_condition)
        delete_fields = set(delete_fields)
        key = {k: key_or_item[k] for k in self.keys.values()}
        # populating expression and attributes
        expressions, attribute_names = self._field_path_to_expression(
            *put_fields.keys(), *extend_arrays.keys(), *increment_fields.keys(),
            *extend_sets.keys(), *remove_from_sets.keys(), *delete_fields, *(conditions.attribute_names() if conditions is not None else [])
        )
        attribute_values = {}
        expression_iterable = iter(expressions)
        set_expressions = []
        for i, (value, expr) in enumerate(zip(put_fields.values(), expression_iterable)):
            attribute_values[f":set_value{i}"] = _recursive_convert(value, to_decimal=True)
            set_expressions.append(f"{expr} = :set_value{i}")
        for i, (value, expr) in enumerate(zip(extend_arrays.values(), expression_iterable)):
            attribute_values[f":extend_value{i}"] = _recursive_convert(list(value), to_decimal=True)
            attribute_values[f":empty_list"] = []
            set_expressions.append(f"{expr} = list_append(if_not_exists({expr}, :empty_list), :extend_value{i})")
        add_expressions = []
        for i, (value, expr) in enumerate(zip(increment_fields.values(), expression_iterable)):
            attribute_values[f":add_value{i}"] = _recursive_convert(value, to_decimal=True)
            add_expressions.append(f"{expr} :add_value{i}")
        for i, (value, expr) in enumerate(zip(extend_sets.values(), expression_iterable)):
            attribute_values[f":insert_value{i}"] = _recursive_convert(value, to_decimal=True)
            add_expressions.append(f"{expr} :insert_value{i}")
        delete_expressions = []
        for i, (value, expr) in enumerate(zip(remove_from_sets.values(), expression_iterable)):
            value = value if isinstance(value, set) else {value}
            attribute_values[f":pop_value{i}"] = _recursive_convert(value, to_decimal=True)
            delete_expressions.append(f"{expr} :pop_value{i}")
        remove_expressions = []
        for i, (value, expr) in enumerate(zip(delete_fields, expression_iterable)):
            remove_expressions.append(f"{expr}")
        expression = " ".join(f"{kw} {', '.join(expr)}" for kw, expr in (("SET", set_expressions), ("ADD", add_expressions), ("DELETE", delete_expressions), ("REMOVE", remove_expressions)) if len(expr) > 0)
        # handle conditions
        if conditions is None:
            condition_expression = None
        else:
            condition_expression = conditions.condition_expression({v: k for k, v in attribute_names.items()}, attribute_values)
        # send call to dynamodb
        try:
            response = await self.table.update_item(
                Key=key,
                UpdateExpression=expression,
                ExpressionAttributeNames=attribute_names,
                ReturnValues=f"ALL_{return_object}" if return_object else "NONE",  # Return the updated values after setting
                **(dict() if len(attribute_values) == 0 else dict(ExpressionAttributeValues=attribute_values)),
                **(dict() if condition_expression is None else dict(ConditionExpression=condition_expression))
                )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ValidationException":
                raise DynamoDBException(str(e))
            elif e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            else:
                raise
        if not return_object:
            return
        else:
            return _recursive_convert(response.get("Attributes"), to_decimal=False)

    async def get_item_fields_async(
            self,
            key_or_item: dict,
            fields: set[str | tuple[str | int]],
            consistent_read: bool=False,
        ) -> dict | None:
        """
        Returns the given fields (or field paths) from the item at given key.
        If the items does not exist, returns None.

        Params
        ------
        table : object
            The dynamodb Table object
        key_or_item : dict
            The item or the key of the item to update.
        fields : set
            the field names or paths to return
            To specify a field path, use a tuple of strings or integers.
        
        Returns
        -------
        dict | None
            The mapping between fields and their values, for the existing fields.
            If the item does not exists, return None.
        """
        key = {k: key_or_item[k] for k in self.keys.values()}
        expressions, attribute_names = self._field_path_to_expression(*fields)
        response = await self.table.get_item(
            Key=key,
            ProjectionExpression=", ".join(expressions),
            ExpressionAttributeNames=attribute_names,
            ConsistentRead=consistent_read,
        )
        if "Item" not in response:
            return None
        item = response.get("Item")
        if item is None:
            return None
        fields = {f: self._extract_item_field_value(item, f) for f in fields if self._field_exists(item, f)}
        return _recursive_convert(fields, to_decimal=False)
