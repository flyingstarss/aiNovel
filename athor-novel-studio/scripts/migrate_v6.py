"""增量迁移 v6：设定表按书隔离。

- worldview / person / person_relation / story_map 增加 outline_id
- 唯一键改为 (outline_id, name)，允许不同书出现同名人物、地点、伏笔
- 回填 person_relation.outline_id

用法：python scripts/migrate_v6.py
"""

import sys
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

COLUMNS = {
    "worldview": "int DEFAULT NULL COMMENT '所属全书大纲，用于按书隔离'",
    "person": "int DEFAULT NULL COMMENT '所属全书大纲，用于按书隔离'",
    "person_relation": "int DEFAULT NULL COMMENT '所属全书大纲，用于按书隔离'",
    "story_map": "int DEFAULT NULL COMMENT '所属全书大纲，用于按书隔离'",
}

INDEXES = {
    "worldview": ("idx_worldview_outline", "outline_id"),
    "person": ("idx_person_outline", "outline_id"),
    "person_relation": ("idx_relation_outline", "outline_id"),
    "story_map": ("idx_story_map_outline", "outline_id"),
}

# 旧唯一键 -> 新唯一键（按书 + 名称）
UNIQUE_KEYS = [
    ("person", "uk_name", "uk_person_outline_name"),
    ("story_map", "uk_map_name", "uk_map_outline_name"),
    ("foreshadow", "uk_foreshadow_name", "uk_foreshadow_outline_name"),
]

BACKFILL_RELATION = """
UPDATE person_relation pr
JOIN person pa ON pa.id = pr.person_id_a
SET pr.outline_id = pa.outline_id
WHERE pr.outline_id IS NULL AND pa.outline_id IS NOT NULL
"""


def _table_columns(cur, table):
    cur.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
        (settings.db_name, table),
    )
    return {row[0] for row in cur.fetchall()}


def _table_indexes(cur, table):
    cur.execute(
        "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
        (settings.db_name, table),
    )
    return {row[0] for row in cur.fetchall()}


def _has_duplicates(cur, table):
    cur.execute(
        f"SELECT 1 FROM `{table}` GROUP BY `outline_id`, `name` "
        "HAVING COUNT(*) > 1 LIMIT 1"
    )
    return cur.fetchone() is not None


def main():
    conn = pymysql.connect(**settings.db_config, database=settings.db_name, autocommit=True)
    cur = conn.cursor()
    try:
        for table, ddl in COLUMNS.items():
            if "outline_id" in _table_columns(cur, table):
                print(f"列已存在，跳过：{table}.outline_id")
                continue
            cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `outline_id` {ddl}")
            print(f"已新增列：{table}.outline_id")

        for table, (index_name, column) in INDEXES.items():
            if index_name in _table_indexes(cur, table):
                print(f"索引已存在，跳过：{index_name}")
                continue
            cur.execute(f"ALTER TABLE `{table}` ADD INDEX `{index_name}` (`{column}`)")
            print(f"已新增索引：{index_name}")

        for table, old_key, new_key in UNIQUE_KEYS:
            indexes = _table_indexes(cur, table)
            if new_key not in indexes:
                if _has_duplicates(cur, table):
                    print(f"存在同名重复数据，暂不添加唯一键：{table}.{new_key}")
                else:
                    cur.execute(
                        f"ALTER TABLE `{table}` ADD UNIQUE KEY `{new_key}` "
                        "(`outline_id`,`name`)"
                    )
                    print(f"已新增唯一键：{new_key}")
            if old_key in indexes:
                cur.execute(f"ALTER TABLE `{table}` DROP INDEX `{old_key}`")
                print(f"已删除旧唯一键：{old_key}")

        cur.execute(BACKFILL_RELATION)
        print(f"回填 person_relation.outline_id {cur.rowcount} 条")
    finally:
        cur.close()
        conn.close()
    print("迁移完成")


if __name__ == "__main__":
    main()
