"""幂等初始化数据库：建库、建全部表并写入违规词种子数据。

用法：
    python scripts/init_db.py
"""

import sys
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"


def split_statements(text: str) -> list[str]:
    statements, buffer = [], []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(buffer).strip().rstrip(";").strip()
            if stmt:
                statements.append(stmt)
            buffer = []
    tail = "\n".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def main():
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    statements = split_statements(sql)

    conn = pymysql.connect(**settings.db_config)
    try:
        cur = conn.cursor()
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{settings.db_name}` "
            "DEFAULT CHARACTER SET utf8mb4"
        )
        conn.select_db(settings.db_name)
        for stmt in statements:
            cur.execute(stmt)
        conn.commit()
        print(f"数据库 {settings.db_name} 初始化完成，执行语句 {len(statements)} 条")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
