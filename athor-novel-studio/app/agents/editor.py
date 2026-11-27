from collections import deque
from typing import TypedDict, List

import pymysql
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field

from app import monitor
from app.agents.writer import parse_short_cast
from app.config import settings
from app.db import connect as db_connect
from app.llm import create_llm

llm = create_llm(settings.llm_temp_editor)

class worldView(BaseModel):
    spacetime: str=Field(description="所处时空")
    rule: str=Field(description="世界规则")
    geoEco: str=Field(description="地理生态")
    history: str=Field(description="既往历史")
    populace: str=Field(description="人群分类")
    socPower: str=Field(description="社会的权力架构")
    econLife: str=Field(description="经济日常")
    culture: str=Field(description="文化和信仰")
    powerSys: str=Field(description="小说里的能力体系")

class perSon(BaseModel):
    name: str=Field(description="姓名")
    age: int=Field(description="年龄")
    gender: str=Field(description="性别")
    appear: str=Field(description="外貌")
    charTr: str=Field(description="性格")
    situat: str=Field(description="处境")
    ability: str=Field(description="能力")
    goal: str=Field(description="核心目标")
    relation: str=Field(description="这个人物和其他人物的关系")

# 人物关系模型
class PersonRel(BaseModel):
    name_a: str = Field(description="第一个人物名字")
    name_b: str = Field(description="第二个人物名字")
    relation_desc: str = Field(description="关系描述，例如：师徒、仇敌、兄妹")
    relation_type: str = Field(description="关系类型：正向 / 敌对 / 中立")

# 打包输出模型：同时输出一批人物 + 一批关系
class PersonBatchOutput(BaseModel):
    person_list: List[perSon] = Field(description="人物列表")
    relation_list: List[PersonRel] = Field(description="人物关系列表")

class personlist(BaseModel):
    person_list: List[perSon] = Field(description="人物列表")

class Agentstate(TypedDict):
    userinput: str
    worldview: worldView
    person_list: list
    is_pass: str
    outline_id: int
    volume_id: int
    volume_ids: list
    short_id: int
    short_ids: list


import pymysql

# 世界观编辑
@monitor.track_step("世界观生成")
def worldEdit(state: Agentstate):
    """这是用于编辑世界观的智能体"""
    userinput = state["userinput"]
    structured_llm = llm.with_structured_output(worldView)
    prompts = [
        SystemMessage(
            "你是一个专业的大纲编辑者，请依据用户的输入生成一份完整的世界观。"
            "用户输入只是故事的起点，不是世界的边界：世界观必须覆盖更广阔的时空、"
            "地理、势力与文化，为后续离开初始地点、跨区域冒险预留足够空间。"
        ),
        HumanMessage(content=f"""【故事起点】
{userinput}

请以此为起点扩展出完整世界观：至少包含多个国家、区域或势力，并设计不同的地理生态与文明形态，不要只围绕起点（如学院、村庄、宗门）展开。""")
    ]
    ai = structured_llm.invoke(prompts)

    # 插入数据库
    spacetime = ai.spacetime
    rule = ai.rule
    geoEco = ai.geoEco
    history = ai.history
    populace = ai.populace
    socPower = ai.socPower
    econLife = ai.econLife
    culture = ai.culture
    powerSys = ai.powerSys

    conn = db_connect()
    cur = conn.cursor()
    outline_id = state.get("outline_id")
    insert_sql = """
    INSERT INTO worldview (spacetime, rule, geoEco, history, populace, socPower, econLife, culture, powerSys, outline_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    demo_data = (
        spacetime,
        rule,
        geoEco,
        history,
        populace,
        socPower,
        econLife,
        culture,
        powerSys,
        outline_id,
    )
    cur.execute(insert_sql, demo_data)
    conn.commit()
    worldview_id = cur.lastrowid

    cur.close()
    conn.close()

    return {"worldview": ai, "worldview_id": worldview_id}


    # 从数据库中读取世界观
def get_all_worldview(outline_id=None):
    conn = None
    cur = None
    try:
        conn = db_connect()
        cur = conn.cursor(pymysql.cursors.DictCursor)  # ✅ DictCursor，查出来是字典，方便映射Pydantic
        if outline_id:
            cur.execute(
                "SELECT * FROM worldview WHERE outline_id = %s ORDER BY id DESC;",
                (outline_id,),
            )
        else:
            cur.execute("SELECT * FROM worldview ORDER BY id DESC;")
        result = cur.fetchall()  # fetchall() 获取全部，返回列表，里面每条是字典
        return result
    except Exception as e:
        print("读取失败：", e)
        return []
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

import hashlib

def sha256_hash(text: str) -> str:
    # 先转字节，再sha256，返回十六进制字符串
    h = hashlib.sha256(text.encode("utf-8"))
    return h.hexdigest()

# 人物生成逻辑： 人物列表——>组装人物关系——>填充人物信息

# 生成人物名称列表
def personList(state: Agentstate):
    content = get_all_worldview(state.get("outline_id"))
    structured_llm = llm.with_structured_output(personlist)
    prompts = [
        SystemMessage("你是一个人物生成专家，擅长生成人物"),
        HumanMessage(content=f"请依据世界观：{content}生成一批人物姓名")
    ]
    ai = structured_llm.invoke(prompts)
    return {"person_list": ai.person_list}

# 构建人物关系
def person_rel(state: Agentstate):
    person_list = state["person_list"]
    structured_llm = llm.with_structured_output(PersonRel)
    prompts = [
        SystemMessage("你是一个人物关系生成专家，擅长构建人物关系"),
        HumanMessage(f"请依据人物列表{person_list}构建一批人物关系")
    ]
    ai = structured_llm.invoke(prompts)

    # 插入数据库
    outline_id = state.get("outline_id")
    scope = f"{outline_id}:" if outline_id else ""
    sorted_names = sorted([ai.name_a, ai.name_b])
    rell = f"{sorted_names[0]}||{sorted_names[1]}"
    id = sha256_hash(scope + rell)
    person_id_a = sha256_hash(scope + ai.name_a)
    person_id_b = sha256_hash(scope + ai.name_b)
    relation_desc = ai.relation_desc
    relation_type = ai.relation_type
    name_a = ai.name_a
    name_b = ai.name_b

    conn = db_connect()
    cur = conn.cursor()
    insert_sql = """
    INSERT INTO person_relation (id, person_id_a, person_id_b, relation_desc, relation_type,name_a,name_b,outline_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        relation_desc = VALUES(relation_desc),
        relation_type = VALUES(relation_type),
        name_a        = VALUES(name_a),
        name_b        = VALUES(name_b),
        outline_id    = COALESCE(outline_id, VALUES(outline_id));
    """
    demo_data = (
        id,
        person_id_a,
        person_id_b,
        relation_desc,
        relation_type,
        name_a,
        name_b,
        outline_id,
    )
    cur.execute(insert_sql, demo_data)
    conn.commit()

    cur.close()
    conn.close()

    return {"is_pass": "ok"}


# 人物信息填充，逻辑是读取数据库里的关系数据表，根据关系和世界观来填充人物的基本信息
@monitor.track_step("人物生成")
def personEdit(state: Agentstate):
    """按「连通人物群 + 群内关系」逐组生成人物信息，并写入 person 表"""

    structured_llm = llm.with_structured_output(PersonBatchOutput)

    LABELS = {
        "spacetime": "所处时空", "rule": "世界规则", "geoEco": "地理生态",
        "history": "既往历史", "populace": "人群分类", "socPower": "权力架构",
        "econLife": "经济日常", "culture": "文化信仰", "powerSys": "能力体系",
    }

    # ---------- 1. 世界观 ----------
    rows = get_all_worldview(state.get("outline_id")) or []
    if not rows:
        raise ValueError("世界观表为空，请先执行 worldEdit 节点")
    latest = rows[0]
    worldview_text = "\n".join(
        f"- {LABELS.get(k, k)}：{v}"
        for k, v in latest.items()
        if k in LABELS and v not in (None, "")
    )

    # ---------- 2. 关系数据 ----------
    def get_all_person_rel():
        conn = None
        cur = None
        try:
            conn = db_connect()
            cur = conn.cursor(pymysql.cursors.DictCursor)
            cur.execute("SELECT * FROM person_relation;")
            return cur.fetchall()
        except Exception as e:
            print("读取失败：", e)
            return []
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    results = get_all_person_rel()

    # ---------- 3. 邻接表 + 连通分量 ----------
    adj = {}
    for rel in results:
        na, nb = rel["name_a"], rel["name_b"]
        adj.setdefault(na, set()).add(nb)
        adj.setdefault(nb, set()).add(na)

    visited, groups = set(), []
    for name in adj:
        if name in visited:
            continue
        queue = deque([name])
        visited.add(name)
        group = []
        while queue:
            node = queue.popleft()
            group.append(node)
            for neighbor in adj[node]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        groups.append(group)

    if not groups:
        print("person_relation 表为空，请先执行 person_rel 节点")
        return {"person_list": []}

    # ---------- 4. 建表 + 落库 ----------
    outline_id = state.get("outline_id")
    CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS person (
        id        CHAR(64)    NOT NULL COMMENT 'sha256(outline_id:name)',
        name      VARCHAR(64) NOT NULL,
        age       INT         DEFAULT NULL,
        gender    VARCHAR(16) DEFAULT NULL,
        appear    TEXT,
        charTr    TEXT,
        situat    TEXT,
        ability   TEXT,
        goal      TEXT,
        relation  TEXT,
        outline_id INT        DEFAULT NULL,
        PRIMARY KEY (id),
        UNIQUE KEY uk_person_outline_name (outline_id, name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """

    INSERT_SQL = """
    INSERT INTO person
        (id, name, age, gender, appear, charTr, situat, ability, goal, relation, outline_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        age      = VALUES(age),
        gender   = VALUES(gender),
        appear   = VALUES(appear),
        charTr   = VALUES(charTr),
        situat   = VALUES(situat),
        ability  = VALUES(ability),
        goal     = VALUES(goal),
        relation = VALUES(relation),
        outline_id = COALESCE(outline_id, VALUES(outline_id));
    """

    system_prompt = (
        "你是一个专业的人物编辑者。你会拿到一份世界观、一组人物姓名，"
        "以及这组人物之间的全部关系。请为每个人物生成符合世界观、且互相呼应的人物档案。"
    )

    all_persons, seen = [], set()
    inserted = 0

    conn = db_connect()
    cur = conn.cursor()

    try:
        cur.execute(CREATE_SQL)
        conn.commit()

        # ---------- 5. 逐组生成 ----------
        for idx, group in enumerate(groups, 1):
            members = "、".join(group)

            rel_lines = [
                f"- {r['name_a']} —— {r['name_b']}：{r['relation_desc']}（{r['relation_type']}）"
                for r in results
                if r["name_a"] in group and r["name_b"] in group
            ]
            relation_text = "\n".join(rel_lines) if rel_lines else "（本组暂无关系记录）"

            human_prompt = f"""【世界观】
{worldview_text}

【本组人物】共 {len(group)} 人：{members}

【本组人物关系】
{relation_text}

请为上述 {len(group)} 位人物逐一生成基本信息，要求：
1. name 必须与上方姓名完全一致，不得新增人物、不得改动姓名；
2. 人物设定需符合世界观，并体现其在关系网中的位置；
3. relation 字段写明该人物与本组其他人的具体关系；
4. 同组人物的年龄、辈分、立场必须自洽；
5. relation_list 请将上方关系原样回填。"""

            ai = structured_llm.invoke([
                SystemMessage(system_prompt),
                HumanMessage(content=human_prompt)
            ])

            batch = []
            for person in ai.person_list:
                if person.name not in group or person.name in seen:
                    continue
                seen.add(person.name)
                all_persons.append(person)
                batch.append((
                    sha256_hash(f"{outline_id}:{person.name}") if outline_id
                    else sha256_hash(person.name),
                    person.name,
                    person.age,
                    person.gender,
                    person.appear,
                    person.charTr,
                    person.situat,
                    person.ability,
                    person.goal,
                    person.relation,
                    outline_id,
                ))

            if batch:
                cur.executemany(INSERT_SQL, batch)
                conn.commit()          # 每组提交一次，前面对的不因后面失败而回滚
                inserted += len(batch)

            missing = [n for n in group if n not in seen]
            if missing:
                print(f"第 {idx} 组有 {len(missing)} 人未生成：{missing}")

    except Exception as e:
        conn.rollback()
        print("写入失败，已回滚：", e)
        raise
    finally:
        cur.close()
        conn.close()

    print(f"共 {len(groups)} 个关系群，写入人物 {inserted} 条")
    return {"person_list": all_persons}


# ------------------------------- 按卷生成人物 -------------------------------

@monitor.track_step("按卷人物生成")
def volumePersonEdit(state: Agentstate):
    """按卷生成人物：结合本卷短纲地点与地图，生成本卷登场人物，记录首次登场卷"""
    volume_id = state.get("volume_id")
    if not volume_id:
        raise ValueError("volumePersonEdit 需要 volume_id")

    vol = _fetch_one("SELECT * FROM volume WHERE id = %s", (volume_id,))
    if not vol:
        raise ValueError(f"volume 表中不存在 id={volume_id} 的分卷")

    shorts = _fetch_all(
        "SELECT seq, title, storyline, location, characters "
        "FROM short_outline WHERE volume_id = %s ORDER BY seq",
        (volume_id,),
    )
    outline_id = vol.get("outline_id")
    if outline_id:
        maps = _fetch_all(
            "SELECT name, type, region, description, inhabitants FROM story_map "
            "WHERE outline_id = %s ORDER BY id",
            (outline_id,),
        )
        existing = _fetch_all(
            "SELECT name FROM person WHERE outline_id = %s ORDER BY name",
            (outline_id,),
        )
    else:
        maps = _fetch_all(
            "SELECT name, type, region, description, inhabitants FROM story_map ORDER BY id"
        )
        existing = _fetch_all("SELECT name FROM person ORDER BY name")

    shorts_text = "\n".join(
        f"- 第{s['seq']}段《{s['title']}》：{s['storyline']}；地点：{s['location']}；"
        f"涉及：{s.get('characters') or '待定'}"
        for s in shorts
    ) or "（本卷暂无短纲）"
    maps_text = "\n".join(
        f"- {m['name']}（{m.get('type') or '地点'}，{m.get('region') or '未知区域'}）："
        f"{m.get('description') or ''}；势力：{m.get('inhabitants') or '无'}"
        for m in maps
    ) or "（暂无地图）"
    existing_names = "、".join(r["name"] for r in existing) or "（暂无）"

    structured_llm = llm.with_structured_output(PersonBatchOutput)
    ai = structured_llm.invoke([
        SystemMessage(
            "你是一位网文人物编辑，负责按单卷的舞台生成该卷登场人物。"
            "人物必须与本卷的地点、势力、冲突匹配，不要提前引入后期角色。"
        ),
        HumanMessage(content=f"""【世界观】
{_worldview_text(outline_id)}

【本卷】
第{vol['volume_no']}卷《{vol['title']}》
- 核心目标：{vol.get('summary') or ''}
- 起始状态：{vol.get('start_state') or ''}
- 结尾局势：{vol.get('end_state') or ''}

【本卷短纲与地点】
{shorts_text}

【地图可选用地点】
{maps_text}

【已有人物（不要重复创建，可复用）】
{existing_names}

要求：
1. 生成 5-10 位本卷核心登场人物；若主角已在已有人物中，直接复用并在 relation_list 中补充关系，不得改名；
2. 人物身份、能力、立场必须与本卷地点和势力相符；
3. 不要提前引入后续卷才出现的角色；
4. relation_list 给出本卷人物之间的关系；
5. 除复用人物外，姓名不得与已有人物重复。""")
    ])

    insert_person_sql = """
    INSERT INTO person
        (id, name, age, gender, appear, charTr, situat, ability, goal, relation,
         first_volume_no, outline_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        age = VALUES(age),
        gender = VALUES(gender),
        appear = VALUES(appear),
        charTr = VALUES(charTr),
        situat = VALUES(situat),
        ability = VALUES(ability),
        goal = VALUES(goal),
        relation = VALUES(relation),
        outline_id = COALESCE(outline_id, VALUES(outline_id)),
        first_volume_no = LEAST(
            COALESCE(first_volume_no, VALUES(first_volume_no)),
            VALUES(first_volume_no)
        );
    """
    insert_rel_sql = """
    INSERT INTO person_relation
        (id, person_id_a, person_id_b, relation_desc, relation_type, name_a, name_b, outline_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        relation_desc = VALUES(relation_desc),
        relation_type = VALUES(relation_type),
        outline_id    = COALESCE(outline_id, VALUES(outline_id));
    """

    conn = _connect()
    cur = conn.cursor()
    try:
        for p in ai.person_list:
            person_id = (
                sha256_hash(f"{outline_id}:{p.name}") if outline_id
                else sha256_hash(p.name)
            )
            cur.execute(insert_person_sql, (
                person_id, p.name, p.age, p.gender, p.appear,
                p.charTr, p.situat, p.ability, p.goal, p.relation,
                vol["volume_no"], outline_id,
            ))
        for r in ai.relation_list:
            sorted_names = sorted([r.name_a, r.name_b])
            pair = "||".join(sorted_names)
            rel_id = sha256_hash(f"{outline_id}:{pair}" if outline_id else pair)
            cur.execute(insert_rel_sql, (
                rel_id,
                sha256_hash(f"{outline_id}:{r.name_a}") if outline_id
                else sha256_hash(r.name_a),
                sha256_hash(f"{outline_id}:{r.name_b}") if outline_id
                else sha256_hash(r.name_b),
                r.relation_desc, r.relation_type, r.name_a, r.name_b,
                outline_id,
            ))
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return {
        "volume_no": vol["volume_no"],
        "person_count": len(ai.person_list),
        "person_names": [p.name for p in ai.person_list],
    }


# =====================================================================
# 大纲 / 分卷 / 短纲 / 章节大纲 / 地图 / 伏笔
# 层级：outline(全书大纲) → volume(分卷) → short_outline(短纲) → chapter_outline(章节大纲)
# =====================================================================


WORLD_LABELS = {
    "spacetime": "所处时空", "rule": "世界规则", "geoEco": "地理生态",
    "history": "既往历史", "populace": "人群分类", "socPower": "权力架构",
    "econLife": "经济日常", "culture": "文化信仰", "powerSys": "能力体系",
}

OUTLINE_LABELS = {
    "title": "书名", "theme": "主题", "logline": "一句话故事",
    "core_conflict": "核心矛盾", "setting": "故事背景",
    "protagonist_arc": "主角弧线", "antagonist_arc": "反派弧线",
    "main_plot": "主线走向", "sub_plots": "支线剧情",
    "act_qi": "起", "act_cheng": "承", "act_zhuan": "转", "act_he": "合",
    "ending": "结局", "keywords": "关键词",
}

VOLUME_LABELS = {
    "volume_no": "卷序号", "title": "卷名", "summary": "本卷梗概",
    "volume_function": "本卷作用", "conflict": "本卷矛盾",
    "start_state": "开卷状态", "end_state": "收卷状态",
    "qi": "起", "cheng": "承", "zhuan": "转", "he": "合",
    "main_characters": "主要出场人物", "key_events": "关键事件",
}

def _connect():
    return db_connect()


def _fetch_all(sql: str, args=None):
    conn = _connect()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute(sql, args or ())
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def _fetch_one(sql: str, args=None):
    conn = _connect()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute(sql, args or ())
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def _row_text(row, labels):
    if not row:
        return "（暂无数据）"
    return "\n".join(
        f"- {labels.get(k, k)}：{row.get(k)}"
        for k in labels
        if row.get(k) not in (None, "")
    )


def _worldview_text(outline_id=None):
    if outline_id:
        row = _fetch_one(
            "SELECT * FROM worldview WHERE outline_id = %s ORDER BY id DESC LIMIT 1",
            (outline_id,),
        )
        if not row:
            # 兼容迁移前的全局世界观（无归属），不读取其他书的世界观
            row = _fetch_one(
                "SELECT * FROM worldview WHERE outline_id IS NULL ORDER BY id DESC LIMIT 1"
            )
    else:
        row = _fetch_one("SELECT * FROM worldview ORDER BY id DESC LIMIT 1")
    if not row:
        return "（暂无世界观记录）"
    return "\n".join(
        f"- {WORLD_LABELS.get(k, k)}：{row[k]}"
        for k in WORLD_LABELS
        if row.get(k) not in (None, "")
    )


def _get_outline(state):
    outline_id = state.get("outline_id")
    if outline_id:
        row = _fetch_one("SELECT * FROM outline WHERE id = %s", (outline_id,))
        if row:
            return row
    return _fetch_one("SELECT * FROM outline ORDER BY id DESC LIMIT 1")


# ------------------------------- 数据模型 -------------------------------

class NovelOutline(BaseModel):
    title: str = Field(description="书名")
    theme: str = Field(description="全书主题")
    logline: str = Field(description="一句话故事梗概")
    core_conflict: str = Field(description="全书核心矛盾")
    setting: str = Field(description="故事背景与舞台")
    protagonist_arc: str = Field(description="主角成长弧线")
    antagonist_arc: str = Field(description="反派或阻力方的弧线")
    main_plot: str = Field(description="主线剧情走向")
    sub_plots: str = Field(description="支线剧情，用分号分隔")
    act_qi: str = Field(description="起：开篇设定与入局")
    act_cheng: str = Field(description="承：矛盾升级与势力扩张")
    act_zhuan: str = Field(description="转：重大转折与反转")
    act_he: str = Field(description="合：高潮与收束")
    ending: str = Field(description="结局")
    keywords: str = Field(description="关键元素/标签，用逗号分隔")


class VolumeItem(BaseModel):
    volume_no: int = Field(description="卷序号，从 1 开始连续编号")
    title: str = Field(description="卷名")
    summary: str = Field(description="卷核心目标，一句话")
    volume_function: str = Field(description="本卷在全书起承转合中的位置：起/承/转/合")
    conflict: str = Field(description="本卷核心冲突，一句话")
    start_state: str = Field(description="卷起始状态：人物处境 + 局势")
    end_state: str = Field(description="卷结尾局势，钩子抛出前的状态")
    qi: str = Field(description="起：入局事件，1-2 句")
    cheng: str = Field(description="承：推进事件，1-2 句")
    zhuan: str = Field(description="转：卷高潮，1-2 句")
    he: str = Field(description="合：卷结尾钩子，1 句")
    main_characters: str = Field(description="卷人物变化：谁变了、怎么变")
    key_events: str = Field(description="3-5 条关键事件，编号列出")


class VolumeBatch(BaseModel):
    volume_list: List[VolumeItem] = Field(description="分卷列表")


class ShortOutlineItem(BaseModel):
    seq: int = Field(description="卷内序号，从 1 开始")
    title: str = Field(description="短纲标题")
    start_state: str = Field(description="本段开头状态：人物处境、地点、当前目标与阻碍")
    storyline: str = Field(description="这段故事的详细走向")
    goal: str = Field(description="这段故事要达成的目标")
    conflict: str = Field(description="核心冲突")
    turning_point: str = Field(description="转折点")
    key_events: str = Field(description="关键事件，用分号分隔")
    antagonist: str | None = Field(default="", description="本段反派：人、势力或困境，写清与主角的冲突点，以及第 3 章如何被解决或退场")
    characters: str = Field(description="本段人物：只列本段实际出场的主要人物，不含已退场角色")
    location: str = Field(description="发生地点")
    result: str = Field(description="这段故事的落点与遗留问题")
    end_state: str = Field(description="本段最终结果：第 3 章结束时必须达到的事件结果与人物状态")


class ShortOutlineBatch(BaseModel):
    short_list: List[ShortOutlineItem] = Field(description="短纲列表")


class ChapterOutlineItem(BaseModel):
    chapter_no: int = Field(description="章节序号，从 1 开始连续编号")
    title: str = Field(description="章节名")
    summary: str = Field(description="本章剧情梗概")
    purpose: str = Field(description="本章的写作目的，要推进什么")
    scene: str = Field(description="本章主要场景")
    characters: str = Field(description="本章出场人物")
    conflict: str = Field(description="本章冲突")
    ending_hook: str = Field(description="章尾钩子，用于承上启下")
    target_words: int = Field(description="建议字数")


class ChapterOutlineBatch(BaseModel):
    chapter_list: List[ChapterOutlineItem] = Field(description="章节大纲列表")


class LocationItem(BaseModel):
    name: str = Field(description="地点名称")
    type: str = Field(description="类型：大陆/国家/城市/山脉/秘境/建筑等")
    parent_name: str = Field(description="上级地点，顶级地点填“无”")
    region: str = Field(description="所属区域")
    description: str = Field(description="地点描述")
    terrain: str = Field(description="地貌")
    climate: str = Field(description="气候")
    resources: str = Field(description="资源物产")
    inhabitants: str = Field(description="居住人群或势力")
    story_function: str = Field(description="在故事中的作用")
    related_events: str = Field(description="关联事件")


class LocationBatch(BaseModel):
    location_list: List[LocationItem] = Field(description="地点列表")


class ForeshadowItem(BaseModel):
    name: str = Field(description="伏笔名称")
    content: str = Field(description="伏笔内容")
    plant_place: str = Field(description="埋设位置，例如：第一卷第三章")
    clue: str = Field(description="线索细节，以何种形式出现")
    reveal_place: str = Field(description="揭晓位置，例如：第三卷结尾")
    payoff: str = Field(description="回收方式与效果")
    related_characters: str = Field(description="关联人物")
    importance: str = Field(description="重要程度：核心/主线/支线")
    status: str = Field(description="状态：未埋设/已埋设/未回收/已回收")


class ForeshadowBatch(BaseModel):
    foreshadow_list: List[ForeshadowItem] = Field(description="伏笔列表")


# ------------------------------- 编辑器 -------------------------------

def save_outline_revision(outline_id, title, content, status="待审核", comment=""):
    """保存一版大纲原文，用于追溯修改记录"""
    if not content:
        return
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO outline_revision (outline_id, title, content, status, comment) "
            "VALUES (%s, %s, %s, %s, %s)",
            (outline_id, title, content, status, comment),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def _save_outline(ai, content="", worldview_id=None):
    """把结构化大纲写入 outline 表，状态重置为待审核，返回大纲 id"""
    conn = _connect()
    cur = conn.cursor()
    insert_sql = """
    INSERT INTO outline
        (title, theme, logline, core_conflict, setting,
         protagonist_arc, antagonist_arc, main_plot, sub_plots,
         act_qi, act_cheng, act_zhuan, act_he, ending, keywords, content)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        id          = LAST_INSERT_ID(id),
        theme       = VALUES(theme),
        logline     = VALUES(logline),
        core_conflict = VALUES(core_conflict),
        setting     = VALUES(setting),
        protagonist_arc = VALUES(protagonist_arc),
        antagonist_arc  = VALUES(antagonist_arc),
        main_plot   = VALUES(main_plot),
        sub_plots   = VALUES(sub_plots),
        act_qi      = VALUES(act_qi),
        act_cheng   = VALUES(act_cheng),
        act_zhuan   = VALUES(act_zhuan),
        act_he      = VALUES(act_he),
        ending      = VALUES(ending),
        keywords    = VALUES(keywords),
        content     = IF(VALUES(content) = '', content, VALUES(content)),
        status         = '待审核',
        review_comment = NULL,
        review_time    = NULL;
    """
    data = (
        ai.title, ai.theme, ai.logline, ai.core_conflict, ai.setting,
        ai.protagonist_arc, ai.antagonist_arc, ai.main_plot, ai.sub_plots,
        ai.act_qi, ai.act_cheng, ai.act_zhuan, ai.act_he, ai.ending, ai.keywords,
        content,
    )
    try:
        cur.execute(insert_sql, data)
        outline_id = cur.lastrowid
        # 生成大纲前先造的世界观，归属到本书，避免后续按 outline_id 查不到
        if worldview_id:
            cur.execute(
                "UPDATE worldview SET outline_id = %s WHERE id = %s",
                (outline_id, worldview_id),
            )
        conn.commit()
        save_outline_revision(outline_id, ai.title, content, "待审核", "生成")
        return outline_id
    finally:
        cur.close()
        conn.close()


def update_outline_content(outline_id, markdown, comment=""):
    """用户编辑大纲原文后，重新提取结构并更新对应记录"""
    markdown = (markdown or "").strip()
    if not markdown:
        raise ValueError("大纲内容不能为空")

    conn = _connect()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cur.execute("SELECT id, title FROM outline WHERE id = %s", (outline_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"outline 表中不存在 id={outline_id} 的大纲")
    finally:
        cur.close()
        conn.close()

    structured = llm.with_structured_output(NovelOutline)
    ai = structured.invoke([
        SystemMessage(
            "你是信息提取器，只从给定大纲中提取字段。"
            "缺失的字段返回空字符串，禁止编造原文没有的剧情。"
            "theme / logline / core_conflict 可高度概括，各不超过 40 字；"
            "act_qi 到 act_he 若原文没有对应内容，一律返回空字符串。"
        ),
        HumanMessage(content=f"请从下面的大纲中提取结构化字段：\n\n{markdown}"),
    ])

    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE outline SET
                title = %s, theme = %s, logline = %s, core_conflict = %s,
                setting = %s, protagonist_arc = %s, antagonist_arc = %s,
                main_plot = %s, sub_plots = %s, act_qi = %s, act_cheng = %s,
                act_zhuan = %s, act_he = %s, ending = %s, keywords = %s,
                content = %s, status = '待审核',
                review_comment = NULL, review_time = NULL
            WHERE id = %s
            """,
            (
                ai.title, ai.theme, ai.logline, ai.core_conflict, ai.setting,
                ai.protagonist_arc, ai.antagonist_arc, ai.main_plot, ai.sub_plots,
                ai.act_qi, ai.act_cheng, ai.act_zhuan, ai.act_he, ai.ending,
                ai.keywords, markdown, outline_id,
            ),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    save_outline_revision(outline_id, ai.title, markdown, "待审核", comment or "用户编辑")
    return outline_id, ai


@monitor.track_step("全书大纲生成")
def outlineEdit(state: Agentstate):
    """大纲编辑：生成全书总体故事走向，写入 outline 表"""
    userinput = state.get("userinput", "")

    structured_llm = llm.with_structured_output(NovelOutline)
    ai = structured_llm.invoke([
        SystemMessage(
            "你是一位资深小说总编，负责把控整部小说的总体故事走向。"
            "请依据世界观和用户需求，产出一份结构完整、起承转合清晰的全书大纲。"
            "用户给出的身份、地点或事件只是故事起点（引子），不是故事边界："
            "你必须主动把舞台扩展到更大的世界，绝不能围绕起点打转。"
        ),
        HumanMessage(content=f"""【世界观】
{_worldview_text()}

【用户需求】
{userinput}

要求：
1. 这是网文，以爽感为主：奇遇、升级、打脸、势力扩张等爽点要明确，节奏明快；
2. 主角最终必须成为本世界观下的最强者或巅峰存在，禁止归于平凡、隐退或牺牲式结局；
3. 大纲只写骨架，不写分幕细节和逐章剧情；
4. theme、logline、core_conflict 各不超过 40 字；
5. protagonist_arc 写清“身份起点 + 性格底色 + 弧光（从……到……，最终登顶）”；
6. antagonist_arc 用 1-2 句写清阻力方的立场与结局；
7. main_plot 用 1-3 句话讲清全书主线；sub_plots 写 2-3 条支线，用分号分隔；
8. act_qi 到 act_he 全部返回空字符串，起承转合留到分卷阶段展开；
9. setting 写故事从起点到终局覆盖的世界范围；ending 用 1 句话写主角登顶；
10. 用户输入只是开篇引子：主线必须离开初始地点、走向更大世界，至少跨越 3 个差异明显的区域。""")
    ])

    outline_id = _save_outline(ai, worldview_id=state.get("worldview_id"))

    draft = {
        "title": ai.title, "theme": ai.theme, "logline": ai.logline,
        "core_conflict": ai.core_conflict, "setting": ai.setting,
        "protagonist_arc": ai.protagonist_arc,
        "antagonist_arc": ai.antagonist_arc,
        "main_plot": ai.main_plot, "sub_plots": ai.sub_plots,
        "act_qi": ai.act_qi, "act_cheng": ai.act_cheng,
        "act_zhuan": ai.act_zhuan, "act_he": ai.act_he,
        "ending": ai.ending, "keywords": ai.keywords,
    }

    # 大纲先以“待审核”状态落库，交由 outlineReview 走人工审核
    return {
        "outline_id": outline_id,
        "status": "待审核",
        "outline_text": _row_text(draft, OUTLINE_LABELS),
        "message": "大纲已生成，请用户审核后再进入分卷编辑",
    }


@monitor.track_step("分卷生成")
def volumeEdit(state: Agentstate):
    """分卷编辑：把全书拆成若干分卷，每卷各有起承转合，写入 volume 表"""
    outline = _get_outline(state)
    if not outline:
        raise ValueError("outline 表中暂无大纲，请先执行 outlineEdit 并完成 outlineReview 审核")

    # 人在环：大纲未经用户审核通过，不继续拆卷
    if outline.get("status") in ("待审核", "已驳回"):
        raise ValueError(
            f"当前大纲状态为“{outline['status']}”，请先执行 outlineReview 完成人工审核"
        )

    structured_llm = llm.with_structured_output(VolumeBatch)
    ai = structured_llm.invoke([
        SystemMessage(
            "你是一位网文分卷结构编辑。全书大纲只提供骨架，"
            "真正的起承转合在这一层展开：每卷都要有完整的起、承、转、合，"
            "并按卷纲模板输出，不允许写成 vague 的梗概。"
        ),
        HumanMessage(content=f"""【世界观】
{_worldview_text(outline["id"])}

【全书大纲】
{_row_text(outline, OUTLINE_LABELS)}

【卷纲模板示例】（只学结构与颗粒度，不要照抄内容）
卷名：山中有玉
卷核心目标：主角获得玉灵，危机降临，打破原本平静的生活。
卷起始状态：林野是普通山村少年，靠采药补贴家里，对修仙只有传闻想象。
卷内关键事件：
1. 林野深入后山禁地采药，塌方中意外发现古玉，玉灵微弱苏醒，与他建立初步绑定。
2. 村中出现怪事，引起仙门外门探子注意，留下传讯信号。
3. 林野与玉灵初次沟通，玉灵警告他藏好玉，不能交给仙门。
4. 宗门使者苏玄到访，表面寻访灵根弟子，一眼锁定林野。
5. 苏玄假意温和，暗中探查古玉，林野心生提防。
卷高潮：苏玄夜晚上门威逼利诱，暗示不交宝物山村将遭祸事。
卷结尾（钩子）：林野连夜告别家人，带着玉灵逃入深山，正式踏上逃亡路。
卷人物变化：林野从懵懂少年第一次见识强者虚伪，生出危机感；玉灵确认他可信。

要求：
1. 将全书拆成 3-6 个分卷，volume_no 从 1 开始连续编号；
2. 每卷必须有完整的起承转合，并映射到字段：summary=卷核心目标；start_state=卷起始状态；qi=起（入局）；cheng=承（推进）；zhuan=转（卷高潮）；he=合（结尾钩子）；end_state=卷结尾局势；main_characters=卷人物变化；key_events=3-5 条关键事件；
3. 关键事件具体到“谁做了什么、结果如何”，编号列出，禁止空泛概括；
4. 每卷都要让主角获得实际收益（实力、资源、身份、势力），突出网文爽感，不写低效日常；
5. 卷与卷之间状态递进，上一卷的 end_state 与下一卷的 start_state 对得上；
6. 舞台随卷推进：第 1 卷可留在初始区域，后续卷必须进入新的国家、城市、秘境或战场，禁止多卷共用同一主场景；
7. 每卷内容控制在 300 字以内，只写卷纲，不写逐章细纲。""")
    ])

    conn = _connect()
    cur = conn.cursor()
    insert_sql = """
    INSERT INTO volume
        (outline_id, volume_no, title, summary, volume_function, conflict,
         start_state, end_state, qi, cheng, zhuan, he,
         main_characters, key_events)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        id            = LAST_INSERT_ID(id),
        title         = VALUES(title),
        summary       = VALUES(summary),
        volume_function = VALUES(volume_function),
        conflict      = VALUES(conflict),
        start_state   = VALUES(start_state),
        end_state     = VALUES(end_state),
        qi            = VALUES(qi),
        cheng         = VALUES(cheng),
        zhuan         = VALUES(zhuan),
        he            = VALUES(he),
        main_characters = VALUES(main_characters),
        key_events    = VALUES(key_events);
    """
    volume_ids = []
    try:
        for v in ai.volume_list:
            cur.execute(insert_sql, (
                outline["id"], v.volume_no, v.title, v.summary,
                v.volume_function, v.conflict, v.start_state, v.end_state,
                v.qi, v.cheng, v.zhuan, v.he,
                v.main_characters, v.key_events,
            ))
            volume_ids.append(cur.lastrowid)
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return {"volume_ids": volume_ids}


@monitor.track_step("细纲生成")
def shortOutlineEdit(state: Agentstate):
    """短纲编辑：把分卷拆成若干故事段落（介于卷纲与章纲之间），写入 short_outline 表"""
    outline = _get_outline(state)
    if not outline:
        outlineEdit(state)
        outline = _get_outline(state)

    volume_id = state.get("volume_id")
    if volume_id:
        volumes = _fetch_all(
            "SELECT * FROM volume WHERE id = %s", (volume_id,)
        )
    else:
        volumes = _fetch_all(
            "SELECT * FROM volume WHERE outline_id = %s ORDER BY volume_no",
            (outline["id"],)
        )
    if not volumes:
        raise ValueError("分卷表为空，请先执行 volumeEdit 节点")

    structured_llm = llm.with_structured_output(ShortOutlineBatch)
    insert_sql = """
    INSERT INTO short_outline
        (volume_id, seq, title, storyline, goal, conflict, turning_point,
         key_events, characters, location, chapter_span, result,
         start_state, end_state, chapter_count, segment_mode)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
    ON DUPLICATE KEY UPDATE
        id           = LAST_INSERT_ID(id),
        title        = VALUES(title),
        storyline    = VALUES(storyline),
        goal         = VALUES(goal),
        conflict     = VALUES(conflict),
        turning_point = VALUES(turning_point),
        key_events   = VALUES(key_events),
        characters   = VALUES(characters),
        location     = VALUES(location),
        chapter_span = VALUES(chapter_span),
        result       = VALUES(result),
        start_state  = VALUES(start_state),
        end_state    = VALUES(end_state),
        chapter_count = VALUES(chapter_count),
        segment_mode = VALUES(segment_mode);
    """

    conn = _connect()
    cur = conn.cursor()
    short_ids = []
    try:
        for vol in volumes:
            ai = structured_llm.invoke([
                SystemMessage(
                    "你是一位短纲编辑，负责把一卷的内容拆成若干个故事段落，"
                    "每个段落固定覆盖 3 章，负责控制这 3 章的开头与最终结果。"
                ),
                HumanMessage(content=f"""【世界观】
{_worldview_text(outline["id"])}

【全书大纲】
{_row_text(outline, OUTLINE_LABELS)}

【本卷】
{_row_text(vol, VOLUME_LABELS)}

要求：
1. 将本卷拆成若干短纲，每段固定覆盖 3 章，seq 从 1 开始连续编号；
2. 每段必须是一个完整的小故事，三章内完成起承转合：第 1 章立目标或结仇，第 2 章冲突升级、追杀或试探，第 3 章正面对决、解决本段主要冲突并交代代价；
3. antagonist 必须明确到具体对象：人、势力或困境（如天灾、断粮、灵田枯死），写清与主角的冲突点；第 3 章结束时该反派必须被击败、解决或明确退场，不能留给下一段；
4. 卷级大反派可以跨短纲贯穿，但相邻两段必须更换执行者或更换手段，不得连续两段由同一个人物主导冲突；
5. 同一配角不得连续两段进入主要冲突；已经退场的角色不得在后续段落反复提及；
6. 每段必须写清 start_state（这 3 章开始时的局面：人物处境、地点、目标、阻碍）
   与 end_state（第 3 章结束时必须达到的结果：事件结果、人物状态变化）；
7. 各短纲合起来要完整覆盖本卷的起承转合；
8. 每个短纲写清详细走向、目标、冲突、转折与落点，中间的推进方式留给写手发挥；
9. 地点要与世界观中的地理设定一致，并写清具体区域名，不要只写“学院”“城市”这类笼统词；
10. 同一卷内的各短纲不得全部集中在同一地点；至少有一个短纲承担“离开原地点、进入新区域”的迁移功能；
11. 按网文节奏推进，每段至少有一个爽点或阶段性胜利，不写低效日常。""")
            ])
            for idx, s in enumerate(sorted(ai.short_list, key=lambda x: int(x.seq)), start=1):
                seq = idx
                start_no = 3 * (seq - 1) + 1
                span = f"第{start_no}-{start_no + 2}章"
                cast = (s.characters or "").strip()
                if (s.antagonist or "").strip():
                    cast = f"反派：{s.antagonist.strip()}；本段人物：{cast}"
                cur.execute(insert_sql, (
                    vol["id"], seq, s.title, s.storyline, s.goal, s.conflict,
                    s.turning_point, s.key_events, cast, s.location,
                    span, s.result, s.start_state, s.end_state, 3,
                ))
                short_id = cur.lastrowid
                short_ids.append(short_id)
                ensure_chapter_placeholders({
                    "id": short_id,
                    "volume_id": vol["id"],
                    "seq": seq,
                    "chapter_count": 3,
                }, cur=cur)
            conn.commit()
    finally:
        cur.close()
        conn.close()

    return {"short_ids": short_ids}


def ensure_chapter_placeholders(short, cur=None):
    """为短纲创建 3 个章节占位（只写章号，标题由写手生成时回填）"""
    count = int((short or {}).get("chapter_count") or 3)
    seq = int((short or {}).get("seq") or 1)
    start_no = 3 * (seq - 1) + 1
    insert = """
    INSERT INTO chapter_outline (short_id, chapter_no, target_words)
    VALUES (%s, %s, %s)
    ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)
    """
    if cur is not None:
        for i in range(count):
            cur.execute(insert, (short["id"], start_no + i, 2500))
        return
    conn = _connect()
    own = conn.cursor()
    try:
        for i in range(count):
            own.execute(insert, (short["id"], start_no + i, 2500))
        conn.commit()
    finally:
        own.close()
        conn.close()


@monitor.track_step("章纲生成")
def chapterOutlineEdit(state: Agentstate):
    """章节大纲编辑：依据短纲生成章节大纲，写入 chapter_outline 表"""
    outline = _get_outline(state)

    short_id = state.get("short_id")
    if short_id:
        shorts = _fetch_all(
            "SELECT * FROM short_outline WHERE id = %s", (short_id,)
        )
    elif state.get("volume_id"):
        shorts = _fetch_all(
            "SELECT * FROM short_outline WHERE volume_id = %s ORDER BY seq",
            (state["volume_id"],)
        )
    else:
        shorts = _fetch_all("SELECT * FROM short_outline ORDER BY volume_id, seq")
    if not shorts:
        raise ValueError("短纲表为空，请先执行 shortOutlineEdit 节点")

    structured_llm = llm.with_structured_output(ChapterOutlineBatch)
    insert_sql = """
    INSERT INTO chapter_outline
        (short_id, chapter_no, title, summary, purpose, scene,
         characters, conflict, ending_hook, target_words)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        id          = LAST_INSERT_ID(id),
        title       = VALUES(title),
        summary     = VALUES(summary),
        purpose     = VALUES(purpose),
        scene       = VALUES(scene),
        characters  = VALUES(characters),
        conflict    = VALUES(conflict),
        ending_hook = VALUES(ending_hook),
        target_words = VALUES(target_words);
    """

    conn = _connect()
    cur = conn.cursor()
    chapter_ids = []
    try:
        for short in shorts:
            vol = _fetch_one(
                "SELECT * FROM volume WHERE id = %s", (short["volume_id"],)
            )
            prev_max = _fetch_one(
                "SELECT COALESCE(MAX(co.chapter_no), 0) AS m "
                "FROM chapter_outline co "
                "JOIN short_outline so ON so.id = co.short_id "
                "WHERE so.volume_id = %s AND so.seq < %s",
                (short["volume_id"], short["seq"]),
            )
            start_no = (prev_max or {}).get("m", 0) + 1
            antagonist, cast = parse_short_cast(short.get("characters"))
            ai = structured_llm.invoke([
                SystemMessage(
                    "你是一位章节大纲编辑，负责把一段短纲拆成可执行的章节大纲，"
                    "让写手能据此直接成文。"
                ),
                HumanMessage(content=f"""【全书大纲】
{_row_text(outline, OUTLINE_LABELS)}

【所属分卷】
{_row_text(vol, VOLUME_LABELS)}

【本段短纲】
- 序号：{short.get('seq')}
- 标题：{short.get('title')}
- 详细走向：{short.get('storyline')}
- 目标：{short.get('goal')}
- 冲突：{short.get('conflict')}
- 转折点：{short.get('turning_point')}
- 关键事件：{short.get('key_events')}
- 本段反派：{antagonist or '未指定'}
- 本段人物：{cast or '未指定'}
- 地点：{short.get('location')}
- 章节范围：{short.get('chapter_span')}
- 段落结果：{short.get('result')}

要求：
1. 按 chapter_span 覆盖的章节数量拆分，chapter_no 从 {start_no} 开始依次递增
   （卷内连续编号，不要每段短纲都从 1 开始）；
2. 这 3 章必须构成一个完整的小故事：第 1 章起（立目标、与反派结仇或冲突爆发），
   第 2 章承（对抗升级、追杀或试探，主角付出代价），
   第 3 章转合（正面对决，解决本段反派或困境，交代代价，留下新钩子）；
3. 第 3 章必须解决本段主要冲突，不得把整段冲突拖到下一段；
4. 每章只使用【本段人物】中的角色；未列入的旧人物不得出场，已退场人物最多用一句回忆带过；
5. 卷级大反派可以出现，但本段必须换执行者或换手段，不得与上一段重复同一主导者；
6. 每章只讲一件事，有明确的场景、冲突与推进；
7. 章尾要留下钩子，与下一章形成牵引；
8. 单章建议字数 2000-3000 字；
9. 不得新增短纲之外的主线走向；
10. 场景要随短纲推进而变化，禁止所有章节都发生在同一地点；scene 必须具体到地点名；
11. 若短纲包含迁移，需安排至少一章写路途或新环境初探，展现世界范围的扩展；
12. 按网文节奏写，每章至少有一个推进点或爽点，章尾钩子要强；
13. target_words 必须在 2000-3000 之间。""")
            ])
            for i, c in enumerate(ai.chapter_list[:3]):
                cur.execute(insert_sql, (
                    short["id"], start_no + i, c.title, c.summary, c.purpose,
                    c.scene, c.characters, c.conflict, c.ending_hook, c.target_words,
                ))
                chapter_ids.append(cur.lastrowid)
            conn.commit()
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return {"is_pass": "ok", "chapter_ids": chapter_ids}


@monitor.track_step("地图生成")
def mapEdit(state: Agentstate):
    """地图编辑：生成故事发生的地点版图，写入 story_map 表"""
    outline = _get_outline(state)

    structured_llm = llm.with_structured_output(LocationBatch)
    ai = structured_llm.invoke([
        SystemMessage(
            "你是一位世界观地图设计师，负责为小说设计地点体系，"
            "地点要服务剧情，而不是单纯罗列风景。"
        ),
        HumanMessage(content=f"""【世界观】
{_worldview_text(outline["id"])}

【全书大纲】
{_row_text(outline, OUTLINE_LABELS)}

要求：
1. 生成 8-15 个地点，按 大陆/国家/城市/山脉/秘境/建筑 形成层级；
2. 顶级地点的 parent_name 填“无”，下级地点的 parent_name 必须是已有地点名；
3. 每个地点说明地貌、气候、资源、居住势力，并与世界观的规则一致；
4. 写清该地点在故事中的作用及关联事件，重要地点要能承载核心冲突；
5. 版图必须覆盖整个故事行程，而不只是开篇区域：至少包含初始地点、2 个以上中后期区域、1 个终局舞台；
6. 初始地点（学院、村庄、宗门等）只能占少数，禁止把 80% 以上地点集中在同一城市周边；
7. 为每次区域迁移设计对应地点与关联事件，让地图随分卷推进逐步展开；
8. 至少 1 个高位区域（大陆/国家/秘境）承载核心冲突与结局。""")
    ])

    conn = _connect()
    cur = conn.cursor()
    insert_sql = """
    INSERT INTO story_map
        (name, type, parent_name, region, description, terrain,
         climate, resources, inhabitants, story_function, related_events, outline_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        id          = LAST_INSERT_ID(id),
        type        = VALUES(type),
        parent_name = VALUES(parent_name),
        region      = VALUES(region),
        description = VALUES(description),
        terrain     = VALUES(terrain),
        climate     = VALUES(climate),
        resources   = VALUES(resources),
        inhabitants = VALUES(inhabitants),
        story_function = VALUES(story_function),
        related_events = VALUES(related_events);
    """
    try:
        for loc in ai.location_list:
            cur.execute(insert_sql, (
                loc.name, loc.type, loc.parent_name, loc.region, loc.description,
                loc.terrain, loc.climate, loc.resources, loc.inhabitants,
                loc.story_function, loc.related_events, outline["id"],
            ))
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return {"is_pass": "ok"}


@monitor.track_step("伏笔生成")
def foreshadowEdit(state: Agentstate):
    """伏笔编辑：设计埋设与回收方案，写入 foreshadow 表"""
    outline = _get_outline(state)

    volumes = []
    if outline:
        volumes = _fetch_all(
            "SELECT * FROM volume WHERE outline_id = %s ORDER BY volume_no",
            (outline["id"],)
        )

    volume_text = "\n\n".join(
        _row_text(v, VOLUME_LABELS) for v in volumes
    ) if volumes else "（暂无分卷）"

    structured_llm = llm.with_structured_output(ForeshadowBatch)
    ai = structured_llm.invoke([
        SystemMessage(
            "你是一位伏笔设计师，负责在故事中埋设线索并规划回收，"
            "保证伏笔既出人意料又合情合理。"
        ),
        HumanMessage(content=f"""【全书大纲】
{_row_text(outline, OUTLINE_LABELS)}

【分卷结构】
{volume_text}

要求：
1. 设计 5-10 条伏笔，覆盖核心、主线、支线三个层级；
2. 每条伏笔写清埋设位置、具体线索形式、揭晓位置与回收方式；
3. 埋设位置和揭晓位置必须落在上述分卷之内，且时间先后合理；
4. 线索要能自然融入剧情，不要为埋伏笔而埋伏笔；
5. 至少 2 条伏笔与中后期地图区域、势力或远行相关，支撑跨区域长线回收；
6. 状态统一填“未回收”。""")
    ])

    conn = _connect()
    cur = conn.cursor()
    insert_sql = """
    INSERT INTO foreshadow
        (outline_id, name, content, plant_place, clue, reveal_place,
         payoff, related_characters, importance, status)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        id           = LAST_INSERT_ID(id),
        content      = VALUES(content),
        plant_place  = VALUES(plant_place),
        clue         = VALUES(clue),
        reveal_place = VALUES(reveal_place),
        payoff       = VALUES(payoff),
        related_characters = VALUES(related_characters),
        importance   = VALUES(importance),
        status       = VALUES(status);
    """
    try:
        for f in ai.foreshadow_list:
            cur.execute(insert_sql, (
                outline["id"] if outline else None,
                f.name, f.content, f.plant_place, f.clue, f.reveal_place,
                f.payoff, f.related_characters, f.importance, f.status,
            ))
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return {"is_pass": "ok"}






















