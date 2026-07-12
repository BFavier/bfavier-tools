import unittest
import asyncio
from uuid import uuid4
from aws_tools.dynamodb import Attr, DynamoDBException, DynamoDB, Table
from aws_tools._check_fail_context import check_fail


class DynamoDBTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """
        create a table and define items
        """
        cls.table_name = "unit-test-"+str(uuid4())
        async def create_table():
            async with DynamoDB() as ddb:
                await ddb.create_table_async(cls.table_name, {"HASH": "id", "RANGE": "event_time"}, {"id": "S", "event_time": "S"})
        asyncio.run(create_table())
        cls.item_id = {"id": str(uuid4()), "event_time": "23h30"}
        cls.item = {**cls.item_id, "field": 10.0, "some_field": "ok", "other_field": True}
        cls.new_item = {**cls.item_id, "field": -1.0, "array_field": [{"nested": 10.0}], "set_field": {"a", "b", "c"}}
        while True:
            cls.another_id = {"id": cls.item_id["id"], "event_time": "21h00"}
            if cls.another_id != cls.item_id:
                break
        cls.another_item = {**cls.another_id, "another_field": 10.0}

    @classmethod
    def tearDownClass(cls):
        """
        Delete the table if it was not done already
        """
        try:
            async def clean_up():
                async with DynamoDB() as ddb:
                    await ddb.delete_table_async(cls.table_name, blocking=False)
            asyncio.run(clean_up())
        except DynamoDBException:
            pass
    
    def setUp(self):
        """
        Before each test case, do nothing
        """
        pass

    def tearDown(self):
        """
        After each test case, delete all items
        """
        async def cleanup():
            async with DynamoDB() as ddb:
                try:
                    table = await Table(ddb, self.table_name)
                except DynamoDBException:
                    pass
                else:
                    await table.batch_delete_items_async(table.scan_all_items_async())
        asyncio.run(cleanup())

    def test_table_api(self):
        """
        Test basic table creation and listing
        """
        async def test():
            async with DynamoDB() as ddb:
                assert self.table_name in await ddb.list_table_names_async()
                assert await ddb.table_exists_async(self.table_name)
                assert not await ddb.table_exists_async("unknown_table")
                with check_fail(DynamoDBException):
                    await ddb.create_table_async(self.table_name, {"HASH": "id", "RANGE": "event_time"}, {"id": "S", "event_time": "S"})
        asyncio.run(test())

    def test_table_deletion(self):
        """
        test table deletion
        """
        async def test():
            async with DynamoDB() as ddb:
                new_table_name = "unit-test-unknown-table-"+str(uuid4())
                await ddb.create_table_async(new_table_name, {"HASH": "id", "RANGE": "event_time"}, {"id": "S", "event_time": "S"})
                assert await ddb.table_exists_async(new_table_name)
                await ddb.delete_table_async(new_table_name)
                assert not await ddb.table_exists_async(new_table_name)
                assert new_table_name not in await ddb.list_table_names_async()
                with check_fail(DynamoDBException):
                    await ddb.delete_table_async(new_table_name)
        asyncio.run(test())

    def test_item_api(self):
        """
        Test basic item API
        """
        async def test():
            async with DynamoDB() as ddb:
                table = await Table(ddb, self.table_name)
                # test missing item behaviour
                assert not await table.item_exists_async(self.item)
                assert not await table.item_exists_async(self.item_id)
                assert await table.get_item_async(self.item_id) is None
                assert await table.delete_item_async(self.item_id, return_object=True) is None  # Fails silently and return None, as the object did not exist
                await table.batch_delete_items_async([self.item_id])  # Fails silently, as there is no verification of item existence
                # test item putting
                assert await table.put_item_async(self.item, return_object=True) is None
                assert await table.item_exists_async(self.item_id)
                await table.batch_put_items_async([self.another_item])
                assert (await table.item_exists_async(self.another_id)) == True
                assert [i async for i in table.batch_get_items_async([self.item, {"id": str(uuid4()), "event_time": "23h30"}, self.another_item], chunk_size=2)] == [self.item, None, self.another_item]
                # check getting item by id or full item
                assert await table.get_item_async(self.item_id) == self.item
                assert await table.get_item_async(self.item) == self.item
                assert await table.get_item_async(self.another_id) == self.another_item
                # check overwrite behaviour
                with check_fail(DynamoDBException):
                    await table.put_item_async(self.item_id)
                assert await table.put_item_async(self.new_item, overwrite=True, return_object=True) == self.item
                assert await table.get_item_async(self.item_id) == self.new_item  # verify that the item has correctly be overwritten
                await table.batch_put_items_async([self.item, self.another_item])
                assert await table.get_item_async(self.item_id) == self.item  # verify that the item has correctly be overwritten
                # check delete behaviour
                assert await table.delete_item_async(self.item_id, return_object=True)
                await table.batch_delete_items_async([self.item_id, self.another_id])
        asyncio.run(test())

    def test_query_scan_api(self):
        """
        test query and scan APIs
        """
        async def test():
            async with DynamoDB() as ddb:
                table = await Table(ddb, self.table_name)
                # test missing items behaviour
                assert (await table.scan_items_paginated_async())[0] == []
                assert (await table.query_items_paginated_async(hash_key=self.item_id["id"], page_start_token=None))[0] == []
                # create the item
                await table.put_item_async(self.item, overwrite=False)
                assert (await table.get_item_async(self.item_id))["event_time"] == "23h30"
                await table.put_item_async(self.another_item, overwrite=False)
                assert (await table.get_item_async(self.another_id))["event_time"] == "21h00"
                assert table.keys["RANGE"] == "event_time"  # event time is the sort key
                # scan all items
                assert all(v in (self.another_item, self.item) for v in (await table.scan_items_paginated_async())[0])
                assert all(v in (self.another_item, self.item) for v in [v async for v in table.scan_all_items_async(conditions=Attr("field").eq(10.0))])
                # query with hash key only
                assert all(v in (self.another_item, self.item) for v in (await table.query_items_paginated_async(hash_key=self.item_id["id"], page_start_token=None))[0])
                assert all(v in (self.another_item, self.item) for v in [v async for v in table.query_all_items_async(hash_key=self.item_id["id"])])
                # query with hash and sort key
                assert (await table.query_items_paginated_async(hash_key=self.item_id["id"], page_start_token=None, sort_key_filter="23"))[0] == [self.item]
                assert (await table.query_items_paginated_async(hash_key=self.item_id["id"], page_start_token=None, sort_key_filter=(None, "21h00")))[0] == [self.another_item]
                assert (await table.query_items_paginated_async(hash_key=self.item_id["id"], page_start_token=None, sort_key_filter=("23h30", None)))[0] == [self.item]
                assert (await table.query_items_paginated_async(hash_key=self.item_id["id"], page_start_token=None, sort_key_filter=("21h00", "23h30")))[0] == [self.another_item, self.item]
                assert (await table.query_items_paginated_async(hash_key=self.item_id["id"], page_start_token=None, sort_key_filter=("21h00", "23h30"), ascending=False))[0] == [self.item, self.another_item]
                # scan with conditions
                assert (await table.scan_items_paginated_async(conditions=Attr("field").eq(10.0) & Attr("some_field").eq("ok")))[0] == [self.item]
                # query with conditions
                assert (await table.query_items_paginated_async(hash_key=self.item_id["id"], page_start_token=None, sort_key_filter=("21h00", "23h30"), conditions=Attr("field").eq(10.0)))[0] == [self.item]
        asyncio.run(test())

    def test_update_item(self):
        """
        test item update api
        """
        async def test():
            async with DynamoDB() as ddb:
                table = await Table(ddb, self.table_name)
                assert (await table.update_item_async(self.item_id, put_fields={"field": 1}, return_object="NEW")) is None  # update does not happen by default if item does not exists
                assert (await table.get_item_fields_async(self.item_id, {"field"})) is None
                await table.update_item_async(self.another_id, put_fields={"field": None}, create_item_if_missing=True)
                assert (await table.get_item_fields_async(self.another_id, {"field"})) == {"field": None}
                # create the item
                await table.put_item_async(self.new_item)
                # modify it
                updated = await table.update_item_async(
                    self.item_id,
                    put_fields={"new_field": 1},
                    increment_fields={("array_field", 0, "nested"): 2},
                    remove_from_sets={"set_field": {"b", "d"}},
                    delete_fields=["field"],
                    return_object="NEW"
                )
                updated.update({"id": "#"})
                assert updated == {'new_field': 1, 'event_time': '23h30', 'id': '#', 'array_field': [{'nested': 12}], 'set_field': {'c', 'a'}}
                assert (await table.update_item_async(self.item_id, put_fields={"wont_work_anyway": 1}, conditions=Attr(("array_field", 0, "nested")).eq(0), return_object="NEW")) is None
                await table.update_item_async(self.item_id, extend_arrays={"array_field": [None]}, extend_sets={"set_field": {"a", "d"}})
                assert (await table.get_item_fields_async(self.item_id, {"array_field", "set_field"})) == {"array_field": [{"nested": 12.0}, None], "set_field": {"a", "c", "d"}}
        asyncio.run(test())

    def test_get_item_fields(self):
        """
        test get_item api
        """
        async def test():
            async with DynamoDB() as ddb:
                table = await Table(ddb, self.table_name)
                # return None on a missing item
                assert (await table.get_item_fields_async(self.item_id, {"field"})) is None
                # create the item
                await table.put_item_async(self.new_item)
                # check that we can get the existing fields
                assert (await table.get_item_fields_async(self.item_id, {"field", ("array_field", 0), "missing_field"})) == {"field": -1, ("array_field", 0): {"nested": 10.0}}
        asyncio.run(test())

    def test_set_behaviour(self):
        """
        Empty sets are not supported by DynamoDB
        When creating an item with an empty set, the field is not saved in dynamodb
        When the set gets empty, the corresponding key is deleted
        When adding items to a set field that do not exist, the field is created
        """
        async def test():
            async with DynamoDB() as ddb:
                table = await Table(ddb, self.table_name)
                item_id = {"id": str(uuid4()), "event_time": "23h30"}
                item = {**item_id, "set_field": set()}
                await table.put_item_async(item)
                await table.update_item_async(item_id, extend_sets={"set_field": {"a", "b"}})
                assert (await table.get_item_fields_async(item_id, {"set_field"})) == {"set_field": {"a", "b"}}
                assert (await table.update_item_async(item_id, remove_from_sets={"set_field": {"a", "b"}}))
                assert (await table.get_item_fields_async(item_id, {"set_field"})) == {}
                assert (await table.get_item_async(item_id).get("set_field")) is None


if __name__ == "__main__":
    unittest.main()
