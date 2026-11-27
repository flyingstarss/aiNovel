"""增量迁移 v4：会话消息记录表，并回填历史会话的用户输入与最近提示。

用法：python scripts/migrate_v4.py
"""

import sys
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

DDL = """
CREATE TABLE IF NOT EXISTS `session_message` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `session_id` varchar(64) NOT NULL COMMENT '所属会话 id',
  `role` varchar(16) NOT NULL COMMENT 'user / assistant / system',
  `content` longtext NOT NULL COMMENT '消息内容',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_session` (`session_id`, `id`),
  CONSTRAINT `fk_message_session` FOREIGN KEY (`session_id`)
    REFERENCES `novel_session` (`session_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
"""

BACKFILL_USER = """
INSERT INTO session_message (session_id, role, content, create_time)
SELECT s.session_id, 'user', s.userinput, s.create_time
FROM novel_session s
WHERE s.userinput IS NOT NULL AND s.userinput <> ''
  AND NOT EXISTS (
    SELECT 1 FROM session_message m WHERE m.session_id = s.session_id
  )
"""

BACKFILL_SYSTEM = """
INSERT INTO session_message (session_id, role, content, create_time)
SELECT s.session_id, 'system', s.message, s.update_time
FROM novel_session s
WHERE s.message IS NOT NULL AND s.message <> ''
  AND NOT EXISTS (
    SELECT 1 FROM session_message m
    WHERE m.session_id = s.session_id AND m.role = 'system'
  )
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
        cur.execute(DDL)
        print("已创建 session_message 表")
        cur.execute(BACKFILL_USER)
        print(f"回填用户输入 {cur.rowcount} 条")
        cur.execute(BACKFILL_SYSTEM)
        print(f"回填系统提示 {cur.rowcount} 条")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
