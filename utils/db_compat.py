import json
import shutil
import sqlite3
from pathlib import Path


def _sqlite_path_from_url(database_url: str) -> Path | None:
    if not database_url.startswith("sqlite://"):
        return None

    sqlite_path = database_url.removeprefix("sqlite://")
    if sqlite_path == ":memory:":
        return None

    return Path(sqlite_path)


def _ensure_backup(db_path: Path, suffix: str) -> None:
    backup_path = db_path.with_suffix(f"{db_path.suffix}.{suffix}")
    if not backup_path.exists():
        shutil.copy2(db_path, backup_path)


def migrate_ai_model_configs_sqlite(database_url: str) -> bool:
    db_path = _sqlite_path_from_url(database_url)
    if db_path is None or not db_path.exists():
        return False

    connection = sqlite3.connect(db_path)
    try:
        columns = connection.execute("PRAGMA table_info(ai_model_configs)").fetchall()
        if not columns:
            return False

        column_names = {column[1] for column in columns}
        column_meta = {column[1]: column for column in columns}
        already_migrated = (
            {"invocation_type", "cli_command"}.issubset(column_names)
            and column_meta["base_url"][3] == 0
            and column_meta["api_key"][3] == 0
        )
        if already_migrated:
            return False

        _ensure_backup(db_path, "config-migration.bak")

        invocation_type_expr = (
            "COALESCE(invocation_type, 'api')" if "invocation_type" in column_names else "'api'"
        )
        cli_command_expr = "cli_command" if "cli_command" in column_names else "NULL"

        connection.execute("BEGIN")
        connection.execute("ALTER TABLE ai_model_configs RENAME TO ai_model_configs_old")
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
        connection.execute(
            f"""
            INSERT INTO ai_model_configs (
                id,
                created_at,
                updated_at,
                task_type,
                name,
                invocation_type,
                base_url,
                api_key,
                model,
                cli_command,
                is_active,
                concurrency
            )
            SELECT
                id,
                created_at,
                updated_at,
                task_type,
                name,
                {invocation_type_expr},
                base_url,
                api_key,
                model,
                {cli_command_expr},
                is_active,
                concurrency
            FROM ai_model_configs_old
            """
        )
        connection.execute("DROP TABLE ai_model_configs_old")
        connection.execute(
            "CREATE INDEX idx_ai_model_configs_task_type ON ai_model_configs (task_type)"
        )
        connection.execute(
            "CREATE INDEX idx_ai_model_configs_is_active ON ai_model_configs (is_active)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX uid_ai_model_configs_task_type_name ON ai_model_configs (task_type, name)"
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def migrate_novels_style_sqlite(database_url: str) -> bool:
    db_path = _sqlite_path_from_url(database_url)
    if db_path is None or not db_path.exists():
        return False

    connection = sqlite3.connect(db_path)
    try:
        columns = connection.execute("PRAGMA table_info(novels)").fetchall()
        if not columns:
            return False

        column_names = {column[1] for column in columns}
        if "style" in column_names:
            return False

        _ensure_backup(db_path, "novels-style-migration.bak")

        connection.execute("BEGIN")
        connection.execute("ALTER TABLE novels ADD COLUMN style JSON")
        connection.execute("UPDATE novels SET style = ? WHERE style IS NULL", (json.dumps(None),))
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def migrate_style_presets_sqlite(database_url: str) -> bool:
    db_path = _sqlite_path_from_url(database_url)
    if db_path is None or not db_path.exists():
        return False

    connection = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

        _ensure_backup(db_path, "style-presets-migration.bak")

        if "style_presets" not in tables:
            connection.execute("BEGIN")
            connection.execute(
                """
                CREATE TABLE style_presets (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    name VARCHAR(255) NOT NULL UNIQUE,
                    builtin_key VARCHAR(100) UNIQUE,
                    positive_prompt TEXT NOT NULL,
                    reference_image VARCHAR(500)
                )
                """
            )
            connection.commit()
            return True

        columns = connection.execute("PRAGMA table_info(style_presets)").fetchall()
        column_names = {column[1] for column in columns}
        if "builtin_key" not in column_names:
            connection.execute("BEGIN")
            connection.execute("ALTER TABLE style_presets ADD COLUMN builtin_key VARCHAR(100)")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uid_style_presets_builtin_key ON style_presets (builtin_key)"
            )
            connection.commit()
            return True

        return False
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
