# SPDX-FileCopyrightText: 2023-present deepset GmbH <info@deepset.ai>
#
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import patch

import numpy as np
import psycopg
import pytest
from haystack.dataclasses.document import ByteStream, Document
from haystack.document_stores.errors import DuplicateDocumentError
from haystack.document_stores.types import DuplicatePolicy
from haystack.testing.document_store import CountDocumentsTest, DeleteDocumentsTest, WriteDocumentsTest
from haystack.utils import Secret

from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore


@pytest.mark.integration
class TestDocumentStore(CountDocumentsTest, WriteDocumentsTest, DeleteDocumentsTest):
    def test_write_documents(self, document_store: PgvectorDocumentStore):
        docs = [Document(id="1")]
        assert document_store.write_documents(docs) == 1
        with pytest.raises(DuplicateDocumentError):
            document_store.write_documents(docs, DuplicatePolicy.FAIL)

    def test_write_blob(self, document_store: PgvectorDocumentStore):
        bytestream = ByteStream(b"test", meta={"meta_key": "meta_value"}, mime_type="mime_type")
        docs = [Document(id="1", blob=bytestream)]
        document_store.write_documents(docs)

        retrieved_docs = document_store.filter_documents()
        assert retrieved_docs == docs

    def test_connection_check_and_recreation(self, document_store: PgvectorDocumentStore):
        original_connection = document_store.connection

        with patch.object(PgvectorDocumentStore, "_connection_is_valid", return_value=False):
            new_connection = document_store.connection

        # verify that a new connection is created
        assert new_connection is not original_connection
        assert document_store._connection == new_connection
        assert original_connection.closed

        assert document_store._cursor is not None
        assert document_store._dict_cursor is not None

        # test with new connection
        with patch.object(PgvectorDocumentStore, "_connection_is_valid", return_value=True):
            same_connection = document_store.connection
            assert same_connection is document_store._connection


@pytest.mark.usefixtures("patches_for_unit_tests")
def test_init(monkeypatch):
    monkeypatch.setenv("PG_CONN_STR", "some_connection_string")

    document_store = PgvectorDocumentStore(
        create_extension=True,
        schema_name="my_schema",
        table_name="my_table",
        embedding_dimension=512,
        vector_function="l2_distance",
        recreate_table=True,
        search_strategy="hnsw",
        hnsw_recreate_index_if_exists=True,
        hnsw_index_creation_kwargs={"m": 32, "ef_construction": 128},
        hnsw_index_name="my_hnsw_index",
        hnsw_ef_search=50,
        keyword_index_name="my_keyword_index",
    )

    assert document_store.create_extension
    assert document_store.schema_name == "my_schema"
    assert document_store.table_name == "my_table"
    assert document_store.embedding_dimension == 512
    assert document_store.vector_function == "l2_distance"
    assert document_store.recreate_table
    assert document_store.search_strategy == "hnsw"
    assert document_store.hnsw_recreate_index_if_exists
    assert document_store.hnsw_index_creation_kwargs == {"m": 32, "ef_construction": 128}
    assert document_store.hnsw_index_name == "my_hnsw_index"
    assert document_store.hnsw_ef_search == 50
    assert document_store.keyword_index_name == "my_keyword_index"


@pytest.mark.usefixtures("patches_for_unit_tests")
def test_to_dict(monkeypatch):
    monkeypatch.setenv("PG_CONN_STR", "some_connection_string")

    document_store = PgvectorDocumentStore(
        create_extension=False,
        table_name="my_table",
        embedding_dimension=512,
        vector_function="l2_distance",
        recreate_table=True,
        search_strategy="hnsw",
        hnsw_recreate_index_if_exists=True,
        hnsw_index_creation_kwargs={"m": 32, "ef_construction": 128},
        hnsw_index_name="my_hnsw_index",
        hnsw_ef_search=50,
        keyword_index_name="my_keyword_index",
    )

    assert document_store.to_dict() == {
        "type": "haystack_integrations.document_stores.pgvector.document_store.PgvectorDocumentStore",
        "init_parameters": {
            "connection_string": {"env_vars": ["PG_CONN_STR"], "strict": True, "type": "env_var"},
            "create_extension": False,
            "table_name": "my_table",
            "schema_name": "public",
            "embedding_dimension": 512,
            "vector_function": "l2_distance",
            "recreate_table": True,
            "search_strategy": "hnsw",
            "hnsw_recreate_index_if_exists": True,
            "language": "english",
            "hnsw_index_creation_kwargs": {"m": 32, "ef_construction": 128},
            "hnsw_index_name": "my_hnsw_index",
            "hnsw_ef_search": 50,
            "keyword_index_name": "my_keyword_index",
        },
    }


def test_from_haystack_to_pg_documents():
    haystack_docs = [
        Document(
            id="1",
            content="This is a text",
            meta={"meta_key": "meta_value"},
            embedding=[0.1, 0.2, 0.3],
            score=0.5,
        ),
        Document(
            id="2",
            content="This is another text",
            meta={"meta_key": "meta_value"},
            embedding=[0.4, 0.5, 0.6],
            score=0.6,
        ),
        Document(
            id="3",
            blob=ByteStream(b"test", meta={"blob_meta_key": "blob_meta_value"}, mime_type="mime_type"),
            meta={"meta_key": "meta_value"},
            embedding=[0.7, 0.8, 0.9],
            score=0.7,
        ),
    ]

    with patch(
        "haystack_integrations.document_stores.pgvector.document_store.PgvectorDocumentStore.__init__"
    ) as mock_init:
        mock_init.return_value = None
        ds = PgvectorDocumentStore(connection_string="test")

    pg_docs = ds._from_haystack_to_pg_documents(haystack_docs)

    assert pg_docs[0]["id"] == "1"
    assert pg_docs[0]["content"] == "This is a text"
    assert pg_docs[0]["blob_data"] is None
    assert pg_docs[0]["blob_meta"] is None
    assert pg_docs[0]["blob_mime_type"] is None
    assert "dataframe" not in pg_docs[0]
    assert pg_docs[0]["meta"].obj == {"meta_key": "meta_value"}
    assert pg_docs[0]["embedding"] == [0.1, 0.2, 0.3]
    assert "score" not in pg_docs[0]

    assert pg_docs[1]["id"] == "2"
    assert pg_docs[1]["content"] == "This is another text"
    assert pg_docs[1]["blob_data"] is None
    assert pg_docs[1]["blob_meta"] is None
    assert pg_docs[1]["blob_mime_type"] is None
    assert "dataframe" not in pg_docs[1]
    assert pg_docs[1]["meta"].obj == {"meta_key": "meta_value"}
    assert pg_docs[1]["embedding"] == [0.4, 0.5, 0.6]
    assert "score" not in pg_docs[1]

    assert pg_docs[2]["id"] == "3"
    assert pg_docs[2]["content"] is None
    assert pg_docs[2]["blob_data"] == b"test"
    assert pg_docs[2]["blob_meta"].obj == {"blob_meta_key": "blob_meta_value"}
    assert pg_docs[2]["blob_mime_type"] == "mime_type"
    assert "dataframe" not in pg_docs[2]
    assert pg_docs[2]["meta"].obj == {"meta_key": "meta_value"}
    assert pg_docs[2]["embedding"] == [0.7, 0.8, 0.9]
    assert "score" not in pg_docs[2]


def test_from_pg_to_haystack_documents():
    pg_docs = [
        {
            "id": "1",
            "content": "This is a text",
            "blob_data": None,
            "blob_meta": None,
            "blob_mime_type": None,
            "meta": {"meta_key": "meta_value"},
            "embedding": np.array([0.1, 0.2, 0.3]),
        },
        {
            "id": "2",
            "content": "This is another text",
            "blob_data": None,
            "blob_meta": None,
            "blob_mime_type": None,
            "meta": {"meta_key": "meta_value"},
            "embedding": np.array([0.4, 0.5, 0.6]),
        },
        {
            "id": "3",
            "content": None,
            "blob_data": b"test",
            "blob_meta": {"blob_meta_key": "blob_meta_value"},
            "blob_mime_type": "mime_type",
            "meta": {"meta_key": "meta_value"},
            "embedding": np.array([0.7, 0.8, 0.9]),
        },
    ]

    ds = PgvectorDocumentStore(connection_string=Secret.from_token("test"))
    haystack_docs = ds._from_pg_to_haystack_documents(pg_docs)

    assert haystack_docs[0].id == "1"
    assert haystack_docs[0].content == "This is a text"
    assert haystack_docs[0].blob is None
    assert haystack_docs[0].meta == {"meta_key": "meta_value"}
    assert haystack_docs[0].embedding == [0.1, 0.2, 0.3]
    assert haystack_docs[0].score is None

    assert haystack_docs[1].id == "2"
    assert haystack_docs[1].content == "This is another text"
    assert haystack_docs[1].blob is None
    assert haystack_docs[1].meta == {"meta_key": "meta_value"}
    assert haystack_docs[1].embedding == [0.4, 0.5, 0.6]
    assert haystack_docs[1].score is None

    assert haystack_docs[2].id == "3"
    assert haystack_docs[2].content is None
    assert haystack_docs[2].blob.data == b"test"
    assert haystack_docs[2].blob.meta == {"blob_meta_key": "blob_meta_value"}
    assert haystack_docs[2].blob.mime_type == "mime_type"
    assert haystack_docs[2].meta == {"meta_key": "meta_value"}
    assert haystack_docs[2].embedding == [0.7, 0.8, 0.9]
    assert haystack_docs[2].score is None


@pytest.mark.integration
def test_hnsw_index_recreation():
    def get_index_oid(document_store, schema_name, index_name):
        sql_get_index_oid = """
            SELECT c.oid
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'i'
            AND n.nspname = %s
            AND c.relname = %s;
        """
        return document_store.cursor.execute(sql_get_index_oid, (schema_name, index_name)).fetchone()[0]

    # create a new schema
    connection_string = "postgresql://postgres:postgres@localhost:5432/postgres"
    schema_name = "test_schema"
    with psycopg.connect(connection_string, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")

    # create a first document store and trigger the creation of the hnsw index
    params = {
        "connection_string": Secret.from_token(connection_string),
        "schema_name": schema_name,
        "table_name": "haystack_test_hnsw_index_recreation",
        "search_strategy": "hnsw",
    }
    ds1 = PgvectorDocumentStore(**params)
    ds1._initialize_table()

    # get the hnsw index oid
    hnws_index_name = "haystack_hnsw_index"
    first_oid = get_index_oid(ds1, ds1.schema_name, hnws_index_name)

    # create second document store with recreation enabled
    ds2 = PgvectorDocumentStore(**params, hnsw_recreate_index_if_exists=True)
    ds2._initialize_table()

    # get the index oid
    second_oid = get_index_oid(ds2, ds2.schema_name, hnws_index_name)

    # verify that oids differ
    assert second_oid != first_oid, "Index was not recreated (OID remained the same)"

    # Clean up: drop the schema after the test
    with psycopg.connect(connection_string, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")


@pytest.mark.integration
def test_create_table_if_not_exists():
    def get_table_oid(document_store, schema_name, table_name):
        sql_get_table_oid = """
            SELECT c.oid
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r'
            AND n.nspname = %s
            AND c.relname = %s;
        """
        return document_store.cursor.execute(sql_get_table_oid, (schema_name, table_name)).fetchone()[0]

    connection_string = "postgresql://postgres:postgres@localhost:5432/postgres"
    schema_name = "test_schema"
    table_name = "test_table"

    # Create a new schema
    with psycopg.connect(connection_string, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {schema_name}")

    document_store = PgvectorDocumentStore(
        connection_string=Secret.from_token(connection_string),
        schema_name=schema_name,
        table_name=table_name,
    )

    document_store._create_table_if_not_exists()

    first_table_oid = get_table_oid(document_store, schema_name, table_name)
    assert first_table_oid is not None, "Table was not created"

    document_store._create_table_if_not_exists()

    second_table_oid = get_table_oid(document_store, schema_name, table_name)

    assert first_table_oid == second_table_oid, "Table was recreated"

    # Clean up: drop the schema after the test
    with psycopg.connect(connection_string, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
