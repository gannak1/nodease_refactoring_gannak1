from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from apps.shared.db.session import engine
from apps.shared.services.connection_use_resolver import (
    ConnectionUseDenied,
    ConnectionUseResolver,
)


def test_postgres_owner_predicate_and_use_lock() -> None:
    schema = f"test_connection_use_{uuid.uuid4().hex}"
    connection_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    try:
        with engine.begin() as setup:
            setup.execute(text(f'CREATE SCHEMA "{schema}"'))
            setup.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            setup.execute(
                text(
                    "CREATE TABLE connections ("
                    "id UUID PRIMARY KEY, user_id UUID NOT NULL, name VARCHAR NOT NULL, "
                    "description TEXT NULL, type VARCHAR NOT NULL, host VARCHAR NOT NULL, "
                    "port INTEGER NOT NULL, database VARCHAR NOT NULL, username VARCHAR NOT NULL, "
                    "encrypted_password TEXT NOT NULL, use_ssh BOOLEAN NOT NULL, "
                    "ssh_host VARCHAR NULL, ssh_port INTEGER NULL, ssh_username VARCHAR NULL, "
                    "ssh_auth_type VARCHAR NULL, encrypted_ssh_password TEXT NULL, "
                    "encrypted_ssh_private_key TEXT NULL)"
                )
            )
            setup.execute(
                text(
                    "INSERT INTO connections "
                    "(id, user_id, name, type, host, port, database, username, "
                    "encrypted_password, use_ssh) "
                    "VALUES (:id, :user_id, 'test-connection', 'postgres', "
                    "'example.invalid', 5432, 'testdb', 'test-user', "
                    "'opaque-ciphertext', false)"
                ),
                {"id": connection_id, "user_id": owner_id},
            )
    except OperationalError:
        pytest.skip("local PostgreSQL is unavailable; connection details omitted")

    owner_connection = engine.connect()
    contender_connection = engine.connect()
    owner_transaction = owner_connection.begin()
    contender_transaction = contender_connection.begin()
    owner_session = Session(
        bind=owner_connection,
        join_transaction_mode="create_savepoint",
    )
    try:
        owner_connection.execute(
            text(f'SET LOCAL search_path TO "{schema}", public')
        )
        contender_connection.execute(
            text(f'SET LOCAL search_path TO "{schema}", public')
        )
        contender_connection.execute(text("SET LOCAL lock_timeout = '250ms'"))

        with pytest.raises(ConnectionUseDenied):
            ConnectionUseResolver(owner_session).resolve(
                connection_id,
                execution_subject_user_id=other_user_id,
            )

        resolved = ConnectionUseResolver(owner_session).resolve(
            connection_id,
            execution_subject_user_id=owner_id,
            lock_for_use=True,
        )
        assert resolved.id == connection_id

        with pytest.raises(DBAPIError):
            contender_connection.execute(
                text(
                    "UPDATE connections SET user_id=:new_owner_id WHERE id=:id"
                ),
                {"new_owner_id": other_user_id, "id": connection_id},
            )
    finally:
        owner_session.close()
        if contender_transaction.is_active:
            contender_transaction.rollback()
        if owner_transaction.is_active:
            owner_transaction.rollback()
        contender_connection.close()
        owner_connection.close()
        try:
            with engine.begin() as cleanup:
                cleanup.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        except OperationalError:
            pass
