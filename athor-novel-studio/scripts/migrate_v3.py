"""增量迁移 v3：大纲原文与版本记录、补充违规词、审核阈值辅助。

用法：python scripts/migrate_v3.py
"""

import sys
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

WORDS = [
    ("儿童色情", "色情低俗", "高", "拦截"),
    ("迷奸", "色情低俗", "高", "拦截"),
    ("卖淫", "色情低俗", "高", "拦截"),
    ("猥亵", "色情低俗", "高", "拦截"),
    ("性侵", "色情低俗", "高", "拦截"),
    ("冰毒", "违法犯罪", "高", "拦截"),
    ("海洛因", "违法犯罪", "高", "拦截"),
    ("大麻", "违法犯罪", "高", "拦截"),
    ("摇头丸", "违法犯罪", "高", "拦截"),
    ("制枪", "违禁物品", "高", "拦截"),
    ("爆炸物", "违禁物品", "高", "拦截"),
    ("炸弹制作", "违禁物品", "高", "拦截"),
    ("恐怖组织", "恐怖暴力", "高", "拦截"),
    ("邪教", "违法犯罪", "中", "人工复核"),
    ("分裂国家", "政治敏感", "高", "拦截"),
    ("颠覆国家", "政治敏感", "高", "拦截"),
    ("侮辱英烈", "政治敏感", "高", "拦截"),
    ("民族仇恨", "歧视侮辱", "高", "拦截"),
    ("种族歧视", "歧视侮辱", "中", "警告"),
    ("拐卖妇女", "违法犯罪", "高", "拦截"),
    ("拐卖儿童", "违法犯罪", "高", "拦截"),
    ("虐待儿童", "暴力血腥", "高", "拦截"),
    ("血腥肢解", "暴力血腥", "高", "拦截"),
    ("详细自杀方法", "暴力血腥", "高", "拦截"),
    ("教唆自残", "暴力血腥", "高", "拦截"),
]


def main():
    conn = pymysql.connect(**settings.db_config, database=settings.db_name)
    cur = conn.cursor()

    cur.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'outline'",
        (settings.db_name,),
    )
    outline_cols = {row[0] for row in cur.fetchall()}
    if "content" not in outline_cols:
        cur.execute("ALTER TABLE `outline` ADD COLUMN `content` LONGTEXT NULL COMMENT '大纲 Markdown 原文'")
        print("added outline.content")
    else:
        print("skip outline.content")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS `outline_revision` (
          `id` int NOT NULL AUTO_INCREMENT,
          `outline_id` int NOT NULL COMMENT '所属大纲',
          `title` varchar(128) DEFAULT NULL COMMENT '书名快照',
          `content` longtext COMMENT '该版本的大纲原文',
          `status` varchar(16) DEFAULT NULL COMMENT '该版本状态',
          `comment` text COMMENT '修改说明',
          `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (`id`),
          KEY `idx_outline` (`outline_id`),
          CONSTRAINT `fk_revision_outline` FOREIGN KEY (`outline_id`)
            REFERENCES `outline` (`id`) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """)
    print("outline_revision ready")

    inserted = 0
    for word, category, level, action in WORDS:
        cur.execute(
            "INSERT IGNORE INTO violation_word (word, category, level, action) "
            "VALUES (%s, %s, %s, %s)",
            (word, category, level, action),
        )
        inserted += cur.rowcount
    conn.commit()
    print(f"violation_word +{inserted}")

    cur.close()
    conn.close()
    print("迁移完成")


if __name__ == "__main__":
    main()
