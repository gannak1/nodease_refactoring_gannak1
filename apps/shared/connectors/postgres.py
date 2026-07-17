# 실제 Postgres(Supabase) 연결 로직
import json
import logging
from io import StringIO
from typing import Any

import paramiko
from apps.shared.services.egress_guard import (
    EgressGuardError,
    ensure_db_probe_allowed,
    ensure_network_target_allowed,
    ensure_ssh_tunnel_allowed,
    safe_db_fetch_batch_size,
)
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sshtunnel import SSHTunnelForwarder

from .base import BaseConnector

logger = logging.getLogger(__name__)

MAX_SCHEMA_TABLES = 100
MAX_SCHEMA_COLUMNS_PER_TABLE = 100
MAX_SCHEMA_FOREIGN_KEYS_PER_TABLE = 50
DB_STATEMENT_TIMEOUT_MS = 5000
DB_CONNECT_TIMEOUT_SECONDS = 5
MAX_DB_FETCH_ROWS = 10000
MAX_DB_FETCH_BYTES = 16 * 1024 * 1024


class PostgresConnector(BaseConnector):
    def __init__(
        self,
        *,
        allow_ssh_tunnel: bool = False,
        allowed_db_ports: frozenset[int] | None = frozenset({5432}),
    ):
        self.allow_ssh_tunnel = allow_ssh_tunnel
        self.allowed_db_ports = allowed_db_ports

    def _create_tunnel_and_engine(self, config):
        """
        SSH 터널과 SQLAlchemy Engine을 생성해서 반환한다.
        Returns:
            (engine, tunnel): tunnel은 SSH 미사용 시 None
        """
        tunnel = None
        db_host = config["host"]
        db_port = int(config.get("port", 5432))
        db_hostaddr = None

        ssh_config = config.get("ssh", {})
        if ssh_config and ssh_config.get("enabled"):
            ensure_ssh_tunnel_allowed(
                True,
                allow_tunnel=self.allow_ssh_tunnel,
            )
            ssh_host, ssh_port, _ssh_hostaddr = ensure_network_target_allowed(
                ssh_config["host"],
                int(ssh_config["port"]),
                allowed_ports=None,
            )
            ssh_params = {
                "ssh_address_or_host": (ssh_host, ssh_port),
                "ssh_username": ssh_config["username"],
                "remote_bind_address": (db_host, db_port),
            }

            # 인증방식에 따른 처리
            if ssh_config.get("auth_type") == "key":
                key_content = ssh_config["private_key"]
                pkey = paramiko.RSAKey.from_private_key(StringIO(key_content))
                ssh_params["ssh_pkey"] = pkey
            else:
                ssh_params["ssh_password"] = ssh_config.get("password")

            # 터널 생성 및 시작
            tunnel = SSHTunnelForwarder(**ssh_params)
            tunnel.start()

            db_host = "127.0.0.1"
            db_port = tunnel.local_bind_port
        else:
            db_host, db_port, db_hostaddr = ensure_network_target_allowed(
                db_host,
                db_port,
                allowed_ports=self.allowed_db_ports,
            )

        db_query = {
            "connect_timeout": str(DB_CONNECT_TIMEOUT_SECONDS),
            "options": (
                f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS} "
                "-c default_transaction_read_only=on"
            ),
        }
        if db_hostaddr:
            db_query["hostaddr"] = db_hostaddr
        db_url = URL.create(
            drivername="postgresql+psycopg2",
            username=config["username"],
            password=config["password"],
            host=db_host,
            port=db_port,
            database=config["database"],
            query=db_query,
        )
        # 직접 연결은 검증된 public IP에 hostaddr로 고정하고, SSH tunnel 경로는 local bind로만 연결한다.
        engine = create_engine(db_url)

        return engine, tunnel

    def check(self, config):
        engine = None
        tunnel = None
        try:
            engine, tunnel = self._create_tunnel_and_engine(config)
            with engine.connect() as conn:
                # 간단한 쿼리 실행으로 연결 및 권한 확인
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error("Postgres connection failed: %s", type(e).__name__)
            raise e
        finally:
            if engine:
                engine.dispose()
            if tunnel:
                tunnel.stop()

    def get_schema_info(self, config):
        engine = None
        tunnel = None
        try:
            engine, tunnel = self._create_tunnel_and_engine(config)

            # SQLAlchemy Inspector를 사용하여 DB 스키마 중립적으로 정보 조회
            inspector = inspect(engine)

            result: list[dict[str, Any]] = []
            # 'public' 스키마의 테이블 목록 조회 (필요시 schema 파라미터 조정 가능)
            table_names = inspector.get_table_names()
            schema_truncated = len(table_names) > MAX_SCHEMA_TABLES
            for table_name in table_names[:MAX_SCHEMA_TABLES]:
                columns = []
                all_columns = inspector.get_columns(table_name)
                columns_truncated = len(all_columns) > MAX_SCHEMA_COLUMNS_PER_TABLE
                for col in all_columns[:MAX_SCHEMA_COLUMNS_PER_TABLE]:
                    columns.append(
                        {
                            "name": col["name"],
                            "type": str(col["type"]),
                        }
                    )

                # Foreign Key 정보 추출
                foreign_keys = []
                all_foreign_keys = inspector.get_foreign_keys(table_name)
                foreign_keys_truncated = (
                    len(all_foreign_keys) > MAX_SCHEMA_FOREIGN_KEYS_PER_TABLE
                )
                for fk in all_foreign_keys[:MAX_SCHEMA_FOREIGN_KEYS_PER_TABLE]:
                    # fk 구조: {
                    #   'name': 'fk_orders_users',
                    #   'constrained_columns': ['user_id'],
                    #   'referred_table': 'users',
                    #   'referred_columns': ['id']
                    # }
                    if fk.get("constrained_columns") and fk.get("referred_columns"):
                        foreign_keys.append(
                            {
                                "column": fk["constrained_columns"][
                                    0
                                ],  # 첫 번째 컬럼만 (단순화)
                                "referenced_table": fk["referred_table"],
                                "referenced_column": fk["referred_columns"][0],
                            }
                        )

                result.append(
                    {
                        "table_name": table_name,
                        "columns": columns,
                        "foreign_keys": foreign_keys,  # FK 정보 추가
                        "columns_truncated": columns_truncated,
                        "foreign_keys_truncated": foreign_keys_truncated,
                    }
                )
            if schema_truncated:
                result.append(
                    {
                        "table_name": "__schema_truncated__",
                        "columns": [],
                        "foreign_keys": [],
                        "schema_truncated": True,
                    }
                )

            return result
        finally:
            if engine:
                engine.dispose()
            if tunnel:
                tunnel.stop()

    def fetch_data(self, config, query, batch_size=1000):
        engine = None
        tunnel = None
        buffered_rows: list[dict[str, Any]] = []
        try:
            ensure_db_probe_allowed(query)
            safe_batch_size = safe_db_fetch_batch_size(batch_size)
            engine, tunnel = self._create_tunnel_and_engine(config)

            with engine.connect() as conn:
                # 사용자 제공 SELECT보다 먼저 read-only와 timeout을 적용한다.
                # row cap 초과는 일부 데이터로 계속 진행하지 않고 실패로 닫는다.
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text(f"SET LOCAL statement_timeout = {DB_STATEMENT_TIMEOUT_MS}"))
                # stream_results=True는 실제 사용자 SELECT에만 적용한다.
                result_proxy = conn.execution_options(stream_results=True).execute(text(query))
                total_rows = 0
                total_bytes = 0

                while True:
                    rows = result_proxy.fetchmany(safe_batch_size)
                    if not rows:
                        break
                    if total_rows + len(rows) > MAX_DB_FETCH_ROWS:
                        raise EgressGuardError("adapter.row_limit_exceeded")
                    total_rows += len(rows)
                    for row in rows:
                        row_dict = dict(row._mapping)
                        row_bytes = len(
                            json.dumps(
                                row_dict,
                                ensure_ascii=False,
                                default=str,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        )
                        if total_bytes + row_bytes > MAX_DB_FETCH_BYTES:
                            raise EgressGuardError("adapter.byte_limit_exceeded")
                        total_bytes += row_bytes
                        buffered_rows.append(row_dict)

        finally:
            if engine:
                engine.dispose()
            if tunnel:
                tunnel.stop()

        # Cap 검증과 connector cleanup이 끝난 결과만 caller에 전달한다.
        yield from buffered_rows
