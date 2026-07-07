"""Single-table store interface + two implementations.

Item shape (DynamoDB single-table style):
    {PK, SK, GSIPK?, GSISK?, type, data, blob_uri?, sha256?}

`InMemoryTable` is the local default. `ScyllaTable` speaks the DynamoDB API via
ScyllaDB Alternator (boto3), with one GSI on GSIPK/GSISK — the same access
patterns, no code change in callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..config import settings

Item = dict[str, Any]


class SingleTable(ABC):
    @abstractmethod
    async def put(self, item: Item) -> None: ...

    @abstractmethod
    async def get(self, pk: str, sk: str) -> Item | None: ...

    @abstractmethod
    async def query(self, pk: str, sk_prefix: str | None = None) -> list[Item]: ...

    @abstractmethod
    async def query_gsi(self, gsipk: str, gsisk_prefix: str | None = None) -> list[Item]: ...

    @abstractmethod
    async def delete(self, pk: str, sk: str) -> None: ...


class InMemoryTable(SingleTable):
    """Process-global dict store. Shared across in-process services in local mode."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], Item] = {}

    async def put(self, item: Item) -> None:
        self._items[(item["PK"], item["SK"])] = dict(item)

    async def get(self, pk: str, sk: str) -> Item | None:
        it = self._items.get((pk, sk))
        return dict(it) if it else None

    async def query(self, pk: str, sk_prefix: str | None = None) -> list[Item]:
        out = [
            dict(v)
            for (p, s), v in self._items.items()
            if p == pk and (sk_prefix is None or s.startswith(sk_prefix))
        ]
        return sorted(out, key=lambda i: i["SK"])

    async def query_gsi(self, gsipk: str, gsisk_prefix: str | None = None) -> list[Item]:
        out = [
            dict(v)
            for v in self._items.values()
            if v.get("GSIPK") == gsipk
            and (gsisk_prefix is None or str(v.get("GSISK", "")).startswith(gsisk_prefix))
        ]
        return sorted(out, key=lambda i: str(i.get("GSISK", "")), reverse=True)

    async def delete(self, pk: str, sk: str) -> None:
        self._items.pop((pk, sk), None)


class ScyllaTable(SingleTable):
    """ScyllaDB Alternator (DynamoDB API) via boto3. Requires extra: infra."""

    def __init__(self) -> None:
        import boto3  # lazy — infra extra only

        self._ddb = boto3.resource(
            "dynamodb",
            endpoint_url=settings.scylla_endpoint,
            region_name=settings.scylla_region,
            aws_access_key_id="none",
            aws_secret_access_key="none",
        )
        self._name = settings.scylla_table
        self._table = self._ddb.Table(self._name)

    def ensure_table(self) -> None:
        import botocore.exceptions

        try:
            self._ddb.create_table(
                TableName=self._name,
                KeySchema=[
                    {"AttributeName": "PK", "KeyType": "HASH"},
                    {"AttributeName": "SK", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "PK", "AttributeType": "S"},
                    {"AttributeName": "SK", "AttributeType": "S"},
                    {"AttributeName": "GSIPK", "AttributeType": "S"},
                    {"AttributeName": "GSISK", "AttributeType": "S"},
                ],
                GlobalSecondaryIndexes=[
                    {
                        "IndexName": "GSI1",
                        "KeySchema": [
                            {"AttributeName": "GSIPK", "KeyType": "HASH"},
                            {"AttributeName": "GSISK", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    }
                ],
                BillingMode="PAY_PER_REQUEST",
            )
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] != "ResourceInUseException":
                raise

    async def _run(self, fn, *a, **k):
        import asyncio

        return await asyncio.to_thread(fn, *a, **k)

    async def put(self, item: Item) -> None:
        clean = {k: v for k, v in item.items() if v is not None}
        await self._run(self._table.put_item, Item=clean)

    async def get(self, pk: str, sk: str) -> Item | None:
        resp = await self._run(self._table.get_item, Key={"PK": pk, "SK": sk})
        return resp.get("Item")

    async def query(self, pk: str, sk_prefix: str | None = None) -> list[Item]:
        from boto3.dynamodb.conditions import Key

        cond = Key("PK").eq(pk)
        if sk_prefix:
            cond = cond & Key("SK").begins_with(sk_prefix)
        resp = await self._run(self._table.query, KeyConditionExpression=cond)
        return resp.get("Items", [])

    async def query_gsi(self, gsipk: str, gsisk_prefix: str | None = None) -> list[Item]:
        from boto3.dynamodb.conditions import Key

        cond = Key("GSIPK").eq(gsipk)
        if gsisk_prefix:
            cond = cond & Key("GSISK").begins_with(gsisk_prefix)
        resp = await self._run(
            self._table.query, IndexName="GSI1", KeyConditionExpression=cond,
            ScanIndexForward=False,
        )
        return resp.get("Items", [])

    async def delete(self, pk: str, sk: str) -> None:
        await self._run(self._table.delete_item, Key={"PK": pk, "SK": sk})


_table: SingleTable | None = None


def get_table() -> SingleTable:
    """Process-wide singleton — in-memory (local) or Scylla (infra)."""
    global _table
    if _table is None:
        _table = InMemoryTable() if settings.is_local else ScyllaTable()
    return _table
