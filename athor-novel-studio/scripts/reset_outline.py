"""按大纲 id 重置生成数据。

用法：
    python scripts/reset_outline.py --outline-id 6          # 预演，只显示将删除的数量
    python scripts/reset_outline.py --outline-id 6 --yes    # 真正执行

可选：
    --with-outline   连大纲本身一起删除
    --with-person    清空 person / person_relation（全局清理）
    --with-map       清空 story_map（全局清理）
"""

import argparse
import sys
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

OUTLINE_SCOPED_SQL = [
    (
        "novel_chapter",
        """
        SELECT COUNT(*) FROM novel_chapter nc
        JOIN chapter_outline co ON nc.chapter_outline_id = co.id
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        WHERE v.outline_id = %s
        """,
    ),
    (
        "chapter_outline",
        """
        SELECT COUNT(*) FROM chapter_outline co
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        WHERE v.outline_id = %s
        """,
    ),
    (
        "short_outline",
        """
        SELECT COUNT(*) FROM short_outline so
        JOIN volume v ON so.volume_id = v.id
        WHERE v.outline_id = %s
        """,
    ),
    ("volume", "SELECT COUNT(*) FROM volume WHERE outline_id = %s"),
    ("foreshadow", "SELECT COUNT(*) FROM foreshadow WHERE outline_id = %s"),
]


def main():
    parser = argparse.ArgumentParser(description="按大纲 id 重置生成数据")
    parser.add_argument("--outline-id", type=int, default=None)
    parser.add_argument("--yes", action="store_true", help="确认执行删除")
    parser.add_argument("--with-outline", action="store_true", help="同时删除大纲本身")
    parser.add_argument("--with-person", action="store_true", help="清空人物与人物关系")
    parser.add_argument("--with-map", action="store_true", help="清空地图")
    args = parser.parse_args()

    conn = pymysql.connect(**settings.db_config, database=settings.db_name)
    cur = conn.cursor()

    if not args.outline_id:
        cur.execute("SELECT id, title, status FROM outline ORDER BY id DESC")
        rows = cur.fetchall()
        print("未指定 --outline-id，当前已有大纲：")
        for r in rows:
            print(f"  --outline-id {r[0]}  《{r[1]}》  状态：{r[2]}")
        print("\n示例：python scripts/reset_outline.py --outline-id 6")
        cur.close()
        conn.close()
        return

    cur.execute("SELECT id, title, status FROM outline WHERE id = %s", (args.outline_id,))
    outline = cur.fetchone()
    if not outline:
        print(f"大纲 id={args.outline_id} 不存在")
        return

    print(f"目标大纲：id={outline[0]} 书名={outline[1]} 状态={outline[2]}")
    total = 0
    for name, sql in OUTLINE_SCOPED_SQL:
        cur.execute(sql, (args.outline_id,))
        count = cur.fetchone()[0]
        total += count
        print(f"  {name}: {count} 条")
    if args.with_outline:
        print("  outline: 1 条")
        total += 1
    if args.with_person:
        cur.execute("SELECT COUNT(*) FROM person")
        print(f"  person: {cur.fetchone()[0]} 条（全局）")
        cur.execute("SELECT COUNT(*) FROM person_relation")
        print(f"  person_relation: {cur.fetchone()[0]} 条（全局）")
    if args.with_map:
        cur.execute("SELECT COUNT(*) FROM story_map")
        print(f"  story_map: {cur.fetchone()[0]} 条（全局）")

    if not args.yes:
        print(f"\n预演完成，共 {total} 条关联数据。加 --yes 才会真正删除。")
        cur.close()
        conn.close()
        return

    try:
        cur.execute(
            """
            DELETE nc FROM novel_chapter nc
            JOIN chapter_outline co ON nc.chapter_outline_id = co.id
            JOIN short_outline so ON co.short_id = so.id
            JOIN volume v ON so.volume_id = v.id
            WHERE v.outline_id = %s
            """, (args.outline_id,),
        )
        cur.execute(
            """
            DELETE co FROM chapter_outline co
            JOIN short_outline so ON co.short_id = so.id
            JOIN volume v ON so.volume_id = v.id
            WHERE v.outline_id = %s
            """, (args.outline_id,),
        )
        cur.execute(
            """
            DELETE so FROM short_outline so
            JOIN volume v ON so.volume_id = v.id
            WHERE v.outline_id = %s
            """, (args.outline_id,),
        )
        cur.execute("DELETE FROM volume WHERE outline_id = %s", (args.outline_id,))
        cur.execute("DELETE FROM foreshadow WHERE outline_id = %s", (args.outline_id,))
        if args.with_outline:
            cur.execute("DELETE FROM outline WHERE id = %s", (args.outline_id,))
        if args.with_person:
            cur.execute("DELETE FROM person_relation")
            cur.execute("DELETE FROM person")
        if args.with_map:
            cur.execute("DELETE FROM story_map")
        conn.commit()
        print("重置完成。")
    except Exception as exc:
        conn.rollback()
        print("重置失败，已回滚：", exc)
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
