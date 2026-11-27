"""增量迁移：章节状态、人物当前状态、伏笔推进记录。

用法：python scripts/migrate_v2.py
"""

import sys
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

COLUMNS = {
    "novel_chapter": [
        ("status", "VARCHAR(32) NOT NULL DEFAULT '已完成'"),
        ("updated_at", "DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    ],
    "person": [
        ("current_state", "TEXT NULL"),
        ("current_location", "VARCHAR(255) NULL"),
        ("last_chapter_no", "INT NULL"),
    ],
    "foreshadow": [
        ("last_chapter_no", "INT NULL"),
    ],
}


def main():
    conn = pymysql.connect(**settings.db_config, database=settings.db_name)
    cur = conn.cursor()
    for table, columns in COLUMNS.items():
        cur.execute(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
            (settings.db_name, table),
        )
        existing = {row[0] for row in cur.fetchall()}
        for name, ddl in columns:
            if name in existing:
                print(f"skip {table}.{name}")
                continue
            cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{name}` {ddl}")
            print(f"added {table}.{name}")
    conn.commit()
    cur.close()
    conn.close()
    print("迁移完成")


if __name__ == "__main__":
    main()
