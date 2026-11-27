"""增量迁移 v5：短纲改为「以 3 章为节点」，新增段落开头/结局与走向选择字段。

用法：python scripts/migrate_v5.py
"""

import sys
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

COLUMNS = {
    "start_state": "text COMMENT '本段开头状态'",
    "end_state": "text COMMENT '本段最终结果（第 3 章必须落到这里）'",
    "chapter_count": "tinyint NOT NULL DEFAULT 3 COMMENT '本段覆盖章数'",
    "segment_mode": "tinyint NOT NULL DEFAULT 0 COMMENT '0=旧机制 1=三章一节点'",
    "plot_options": "longtext COMMENT '3 个候选走向（JSON）'",
    "plot_choice_no": "tinyint DEFAULT NULL COMMENT '选中的走向序号 1-3'",
    "plot_choice_mode": "varchar(16) DEFAULT NULL COMMENT 'manual=人工选定 auto=模型自行处理'",
    "plot_choice": "longtext COMMENT '选中走向的文本快照'",
}

BACKFILL_COUNT = """
UPDATE short_outline s
SET s.chapter_count = (
  SELECT COUNT(*) FROM chapter_outline c WHERE c.short_id = s.id
)
WHERE EXISTS (SELECT 1 FROM chapter_outline c WHERE c.short_id = s.id)
  AND s.segment_mode = 0
"""


def main():
    conn = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        charset="utf8mb4",
        autocommit=True,
    )
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'short_outline'",
            (settings.db_name,),
        )
        existing = {r[0] for r in cur.fetchall()}
        for name, ddl in COLUMNS.items():
            if name in existing:
                print(f"列已存在，跳过：{name}")
                continue
            cur.execute(
                f"ALTER TABLE `short_outline` ADD COLUMN `{name}` {ddl} AFTER `result`"
            )
            print(f"已新增列：{name}")

        cur.execute(BACKFILL_COUNT)
        print(f"回填旧短纲章数 {cur.rowcount} 条")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
