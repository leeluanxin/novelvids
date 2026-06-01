import sqlite3
from pathlib import Path

from utils.db_compat import migrate_ai_model_configs_sqlite


def _create_legacy_db(db_path: Path):
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE ai_model_configs (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                task_type INT NOT NULL,
                name VARCHAR(100) NOT NULL,
                base_url VARCHAR(500) NOT NULL,
                api_key VARCHAR(500) NOT NULL,
                model VARCHAR(200) NOT NULL,
                is_active INT NOT NULL DEFAULT 0,
                concurrency INT NOT NULL DEFAULT 1
            )
            """
        )
        connection.execute(
            "CREATE INDEX idx_ai_model_configs_task_type ON ai_model_configs (task_type)"
        )
        connection.execute(
            "CREATE INDEX idx_ai_model_configs_is_active ON ai_model_configs (is_active)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX uid_ai_model_configs_task_type_name ON ai_model_configs (task_type, name)"
        )
        connection.execute(
            """
            INSERT INTO ai_model_configs (
                task_type,
                name,
                base_url,
                api_key,
                model,
                is_active,
                concurrency
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "legacy-config", "https://legacy.example.com", "legacy-key", "legacy-model", 1, 2),
        )
        connection.commit()
    finally:
        connection.close()


def test_migrate_ai_model_configs_sqlite_upgrades_legacy_schema(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)

    migrated = migrate_ai_model_configs_sqlite(f"sqlite://{db_path}")

    assert migrated is True
    assert db_path.with_suffix(".db.config-migration.bak").exists()

    connection = sqlite3.connect(db_path)
    try:
        columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(ai_model_configs)").fetchall()
        }
        assert "invocation_type" in columns
        assert "cli_command" in columns
        assert columns["base_url"][3] == 0
        assert columns["api_key"][3] == 0

        row = connection.execute(
            "SELECT name, invocation_type, base_url, api_key, model, cli_command, is_active, concurrency FROM ai_model_configs"
        ).fetchone()
        assert row == (
            "legacy-config",
            "api",
            "https://legacy.example.com",
            "legacy-key",
            "legacy-model",
            None,
            1,
            2,
        )
    finally:
        connection.close()


def test_migrate_ai_model_configs_sqlite_is_noop_for_current_schema(tmp_path: Path):
    db_path = tmp_path / "current.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE ai_model_configs (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                task_type INT NOT NULL,
                name VARCHAR(100) NOT NULL,
                invocation_type VARCHAR(20) NOT NULL DEFAULT 'api',
                base_url VARCHAR(500),
                api_key VARCHAR(500),
                model VARCHAR(200) NOT NULL,
                cli_command VARCHAR(500),
                is_active INT NOT NULL DEFAULT 0,
                concurrency INT NOT NULL DEFAULT 1
            )
            """
        )
        connection.commit()
    finally:
        connection.close()

    migrated = migrate_ai_model_configs_sqlite(f"sqlite://{db_path}")

    assert migrated is False
    assert not db_path.with_suffix(".db.config-migration.bak").exists()
