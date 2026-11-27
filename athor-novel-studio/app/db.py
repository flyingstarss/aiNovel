"""统一 MySQL 访问层：连接池、查询与执行。"""

import queue
from contextlib import contextmanager

import pymysql

from app.config import settings

# 复用连接：借出时 ping 探活，归还时回滚未提交事务
_pool: "queue.LifoQueue" = queue.LifoQueue(maxsize=max(1, settings.db_pool_size))


def _raw_connect(with_db=True):
    config = settings.db_config
    if with_db:
        config["database"] = settings.db_name
    return pymysql.connect(**config)


class PooledConnection:
    """连接池代理：close() 把连接归还池中，而不是真正断开"""

    def __init__(self, raw):
        self._raw = raw
        self._closed = False

    def __getattr__(self, name):
        return getattr(self._raw, name)

    def cursor(self, *args, **kwargs):
        return self._raw.cursor(*args, **kwargs)

    def commit(self):
        return self._raw.commit()

    def rollback(self):
        return self._raw.rollback()

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._raw.rollback()
        except Exception:
            pass
        try:
            _pool.put_nowait(self._raw)
            return
        except queue.Full:
            pass
        try:
            self._raw.close()
        except Exception:
            pass


def connect(with_db=True):
    # 建库等一次性场景不进入连接池
    if not with_db:
        return _raw_connect(False)
    try:
        raw = _pool.get_nowait()
    except queue.Empty:
        return PooledConnection(_raw_connect(True))
    # 连接可能因 wait_timeout 被服务端断开，借出前先探活
    try:
        raw.ping(reconnect=True)
    except Exception:
        try:
            raw.close()
        except Exception:
            pass
        return PooledConnection(_raw_connect(True))
    return PooledConnection(raw)


@contextmanager
def cursor(dict_rows=True, with_db=True):
    conn = connect(with_db=with_db)
    cur = conn.cursor(pymysql.cursors.DictCursor) if dict_rows else conn.cursor()
    try:
        yield conn, cur
    finally:
        cur.close()
        conn.close()


def fetch_one(sql, params=None):
    with cursor() as (_, cur):
        cur.execute(sql, params or ())
        return cur.fetchone()


def fetch_all(sql, params=None):
    with cursor() as (_, cur):
        cur.execute(sql, params or ())
        return cur.fetchall()


def execute(sql, params=None, many=False):
    with cursor(dict_rows=False) as (conn, cur):
        if many:
            cur.executemany(sql, params or [])
        else:
            cur.execute(sql, params or ())
        conn.commit()
        return cur.rowcount
