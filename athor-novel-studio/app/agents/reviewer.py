from typing import TypedDict

import pymysql
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from app import monitor
from app.agents.writer import parse_short_cast
from app.config import settings
from app.db import connect as db_connect
from app.llm import create_llm

llm = create_llm(settings.llm_temp_reviewer)

CONSISTENCY_THRESHOLD = 75

# 一致性加权评分：细纲符合度 40%、人物一致性 30%、伏笔处理 20%、前文连贯 10%
CONSISTENCY_WEIGHTS = {
    "outline": 0.40,
    "character": 0.30,
    "foreshadow": 0.20,
    "continuity": 0.10,
}


OUTLINE_LABELS = {
    "title": "书名", "theme": "主题", "logline": "一句话故事",
    "core_conflict": "核心矛盾", "setting": "故事背景",
    "protagonist_arc": "主角弧线", "antagonist_arc": "反派弧线",
    "main_plot": "主线走向", "sub_plots": "支线剧情",
    "act_qi": "起", "act_cheng": "承", "act_zhuan": "转", "act_he": "合",
    "ending": "结局", "keywords": "关键词",
    "status": "审核状态", "review_comment": "审核意见",
}


class ReviewState(TypedDict):
    outline_id: int
    review_decision: str
    review_comment: str
    novel_chapter_id: int


class ViolationResult(BaseModel):
    passed: bool = Field(description="是否通过违规审核")
    risk_level: str = Field(description="风险等级：无/低/中/高")
    matched_words: str = Field(description="命中的违规词，用分号分隔，无则填“无”")
    issues: str = Field(description="存在的违规问题，无则填“无”")
    suggestion: str = Field(description="修改建议，无则填“无”")


class ConsistencyResult(BaseModel):
    outline_score: int | None = Field(default=None, description="细纲符合度评分，0-100")
    character_score: int | None = Field(default=None, description="人物一致性评分，0-100")
    foreshadow_score: int | None = Field(default=None, description="伏笔处理评分，0-100")
    continuity_score: int | None = Field(default=None, description="前文连贯性评分，0-100")
    outline_consistency: str = Field(default="", description="与卷纲/短纲/章纲的符合情况")
    character_consistency: str = Field(default="", description="人物言行、关系、设定是否符合人物档案")
    foreshadow_handling: str = Field(default="", description="伏笔处理是否合理")
    continuity_check: str = Field(default="", description="与前文摘要的连贯情况")
    issues: str = Field(default="无", description="发现的问题，逐条列出，无则填“无”")
    suggestion: str = Field(default="无", description="具体修改建议")


def _clamp_score(value):
    """把模型给出的分数限制在 0-100；未返回评分时返回 None"""
    if value is None:
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, value))


def _weighted_score(ai: ConsistencyResult):
    """按固定权重折算总分；缺失维度不计入，并按剩余权重归一化"""
    raw = {
        "outline": _clamp_score(ai.outline_score),
        "character": _clamp_score(ai.character_score),
        "foreshadow": _clamp_score(ai.foreshadow_score),
        "continuity": _clamp_score(ai.continuity_score),
    }
    scored = {k: v for k, v in raw.items() if v is not None}
    if not scored:
        raise ValueError("一致性审核未返回任何维度评分，请重试")
    used_weight = sum(CONSISTENCY_WEIGHTS[k] for k in scored)
    total = round(
        sum(v * CONSISTENCY_WEIGHTS[k] for k, v in scored.items()) / used_weight
    )
    return max(0, min(100, total)), raw


def _score_text(scores: dict, key: str) -> str:
    value = scores.get(key)
    return "未评分" if value is None else f"{value}分"


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


def _invoke_structured(runnable, messages, schema):
    """结构化输出偶发为空或字段缺失时重试，仍失败则改用 JSON 模式兜底"""
    for _ in range(2):
        try:
            result = runnable.invoke(messages)
        except Exception:
            result = None
        if result is not None:
            return result
    try:
        result = llm.with_structured_output(
            schema, method="json_mode"
        ).invoke(messages)
    except Exception:
        result = None
    if result is None:
        raise ValueError("模型未返回结构化审核结果，请重试")
    return result


def _save_review(target_type, target_id, review_type, passed, risk_level, issues, suggestion, reviewer):
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO review_record
                (target_type, target_id, review_type, passed, risk_level,
                 issues, suggestion, reviewer)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (target_type, target_id, review_type, 1 if passed else 0,
             risk_level, issues, suggestion, reviewer)
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def _outline_text(row):
    return "\n".join(
        f"- {OUTLINE_LABELS.get(k, k)}：{row.get(k)}"
        for k in OUTLINE_LABELS
        if row.get(k) not in (None, "")
    )


def _chapter_row(novel_chapter_id=None):
    sql = """
    SELECT nc.*, co.title AS outline_title, co.summary AS outline_summary,
           co.purpose, co.scene, co.characters AS outline_characters,
           co.conflict AS outline_conflict, co.ending_hook, co.target_words,
           so.seq AS short_seq, so.title AS short_title,
           so.storyline AS short_storyline, so.location AS short_location,
           so.start_state AS short_start_state, so.end_state AS short_end_state,
           so.plot_choice, so.chapter_count AS short_chapter_count,
           so.characters AS short_characters,
           (SELECT MIN(c2.chapter_no) FROM chapter_outline c2
            WHERE c2.short_id = co.short_id) AS short_start_no,
           v.volume_no, v.title AS volume_title, v.outline_id
    FROM novel_chapter nc
    JOIN chapter_outline co ON nc.chapter_outline_id = co.id
    JOIN short_outline so ON co.short_id = so.id
    JOIN volume v ON so.volume_id = v.id
    WHERE nc.content IS NOT NULL AND nc.content <> ''
    """
    if novel_chapter_id:
        return _fetch_one(sql + " AND nc.id = %s", (novel_chapter_id,))
    return _fetch_one(sql + " ORDER BY nc.id DESC LIMIT 1")


def _person_text(outline_id=None):
    sql = "SELECT name, gender, age, appear, charTr, situat, ability, goal FROM person"
    args = ()
    if outline_id:
        sql += " WHERE outline_id = %s"
        args = (outline_id,)
    rows = _fetch_all(sql, args)
    if not rows:
        return "（暂无人物记录）"
    return "\n".join(
        f"- {r['name']}（{r.get('gender') or '未知'}，{r.get('age') or '?'}岁）："
        f"外貌 {r.get('appear') or '未知'}；性格 {r.get('charTr') or '未知'}；"
        f"处境 {r.get('situat') or '未知'}；能力 {r.get('ability') or '未知'}；"
        f"目标 {r.get('goal') or '未知'}"
        for r in rows
    )


def _relation_text(outline_id=None):
    if outline_id:
        rows = _fetch_all(
            "SELECT name_a, name_b, relation_desc, relation_type "
            "FROM person_relation WHERE outline_id = %s",
            (outline_id,),
        )
    else:
        rows = _fetch_all(
            "SELECT name_a, name_b, relation_desc, relation_type FROM person_relation"
        )
    if not rows:
        return "（暂无人物关系记录）"
    return "\n".join(
        f"- {r['name_a']} —— {r['name_b']}：{r['relation_desc']}（{r['relation_type']}）"
        for r in rows
    )


def _foreshadow_text(outline_id=None):
    sql = (
        "SELECT name, content, plant_place, reveal_place, importance, status "
        "FROM foreshadow"
    )
    args = ()
    if outline_id:
        sql += " WHERE outline_id = %s"
        args = (outline_id,)
    rows = _fetch_all(sql, args)
    if not rows:
        return "（暂无伏笔记录）"
    return "\n".join(
        f"- {r['name']}【{r.get('importance') or '支线'}·{r.get('status') or '未回收'}】："
        f"{r.get('content')}；埋设于 {r.get('plant_place')}；揭晓于 {r.get('reveal_place')}"
        for r in rows
    )


def _previous_summaries(chapter, limit=3):
    rows = _fetch_all(
        """
        SELECT nc.chapter_no, nc.title, nc.summary
        FROM novel_chapter nc
        JOIN chapter_outline co ON nc.chapter_outline_id = co.id
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        WHERE v.outline_id = %s
          AND (v.volume_no, so.seq, co.chapter_no) < (%s, %s, %s)
          AND nc.summary IS NOT NULL AND nc.summary <> ''
        ORDER BY v.volume_no DESC, so.seq DESC, co.chapter_no DESC
        LIMIT %s
        """,
        (chapter.get("outline_id"), chapter["volume_no"], chapter["short_seq"],
         chapter["chapter_no"], limit)
    )
    return list(reversed(rows))


def _summary_text(summaries):
    if not summaries:
        return "（暂无前文摘要）"
    return "\n\n".join(
        f"【第{s['chapter_no']}章《{s['title']}》】\n{s['summary']}"
        for s in summaries
    )


# ----------------------------- 1. 大纲人工审核 -----------------------------

def outlineReview(state: ReviewState):
    """大纲审核：把大纲交给用户审核，用户确认后通过或驳回"""
    outline_id = state.get("outline_id")
    if outline_id:
        row = _fetch_one("SELECT * FROM outline WHERE id = %s", (outline_id,))
    else:
        row = _fetch_one("SELECT * FROM outline ORDER BY id DESC LIMIT 1")
    if not row:
        raise ValueError("outline 表中暂无大纲，请先执行 outlineEdit")

    decision = (state.get("review_decision") or "").strip()
    comment = state.get("review_comment") or ""

    # 未给出审核结论时，只返回草稿，等待人工确认
    if not decision:
        return {
            "outline_id": row["id"],
            "status": row.get("status") or "待审核",
            "outline_text": _outline_text(row),
            "message": "请用户审核上述大纲，确认后传入 review_decision='通过' 或 '驳回'",
        }

    if decision not in ("通过", "驳回"):
        raise ValueError("review_decision 仅支持：通过 / 驳回")

    passed = decision == "通过"
    status = "已通过" if passed else "已驳回"

    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE outline SET status = %s, review_comment = %s, review_time = NOW() WHERE id = %s",
            (status, comment, row["id"])
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    _save_review(
        "outline", row["id"], "human_outline", passed, None,
        comment or ("用户审核通过" if passed else "用户驳回大纲"),
        "请按审核意见修改或重新生成大纲" if not passed else "可进入分卷编辑",
        "user",
    )

    return {
        "outline_id": row["id"],
        "status": status,
        "review_comment": comment,
    }


# ----------------------------- 2. 违规内容审核 -----------------------------

@monitor.track_step("违规内容审核")
def contentViolationCheck(state: ReviewState):
    """小说内容审核：违规词表命中 + 大模型语义复核"""
    chapter = _chapter_row(state.get("novel_chapter_id"))
    if not chapter:
        raise ValueError("novel_chapter 表中没有可审核的正文，请先执行 novelWriter")

    words = _fetch_all(
        "SELECT word, category, level, action FROM violation_word ORDER BY id"
    )
    hits = [
        f"{w['word']}（{w.get('category') or '未分类'}·{w.get('level') or '中'}·{w.get('action') or '人工复核'}）"
        for w in words
        if w["word"] and w["word"] in chapter["content"]
    ]
    word_text = "\n".join(hits) if hits else "（词表未命中）"

    structured_llm = llm.with_structured_output(ViolationResult)
    ai = _invoke_structured(structured_llm, [
        SystemMessage(
            "你是一位内容安全审核员，负责审核小说正文是否包含色情低俗、暴力血腥、"
            "违法犯罪、违禁物品、恐怖暴力、歧视侮辱等违规内容。"
            "对规避式表达（谐音、拼音、拆字、隐喻）也要识别。"
        ),
        HumanMessage(content=f"""【正文】
{chapter['content']}

【违规词表命中情况】
{word_text}

要求：
1. 结合词表命中情况和正文语义，给出是否通过；
2. 命中“高”等级违规词或存在明确违规描写时，必须判定不通过；
3. matched_words 汇总命中的违规词，无则填“无”；
4. issues 说明具体位置、内容和违规点；
5. suggestion 给出可执行的修改方向，不要直接改写正文。""")
    ], ViolationResult)

    # 词表命中即拦截，不因模型判断宽松而放过
    passed = ai.passed and not hits
    risk_level = ai.risk_level
    if hits and risk_level in ("无", "低"):
        risk_level = "中"
    issues = ai.issues
    if hits:
        issues = f"词表命中：{'；'.join(hits)}；" + (issues or "")
    matched_words = ai.matched_words if not hits else "；".join(
        w["word"] for w in words if w["word"] and w["word"] in chapter["content"]
    )

    _save_review(
        "chapter", chapter["id"], "violation", passed, risk_level,
        issues, ai.suggestion, "system",
    )

    return {
        "novel_chapter_id": chapter["id"],
        "passed": passed,
        "risk_level": risk_level,
        "matched_words": matched_words,
        "issues": issues,
        "suggestion": ai.suggestion,
    }


# --------------------------- 3. 细纲一致性审核 ---------------------------

@monitor.track_step("内容一致性审核")
def contentConsistencyCheck(state: ReviewState):
    """小说内容审核：核对正文是否符合卷纲/短纲/章纲、人物设定与伏笔安排"""
    chapter = _chapter_row(state.get("novel_chapter_id"))
    if not chapter:
        raise ValueError("novel_chapter 表中没有可审核的正文，请先执行 novelWriter")

    structured_llm = llm.with_structured_output(ConsistencyResult)
    if (chapter.get("outline_summary") or "").strip():
        brief_block = f"""【本章章纲】
- 章节名：{chapter.get('outline_title')}
- 剧情梗概：{chapter.get('outline_summary')}
- 写作目的：{chapter.get('purpose')}
- 场景：{chapter.get('scene')}
- 应出场人物：{chapter.get('outline_characters')}
- 本章冲突：{chapter.get('outline_conflict')}
- 章尾钩子：{chapter.get('ending_hook')}
"""
        outline_rule = "1. 检查正文是否按章纲推进，是否遗漏关键事件、写偏主线；"
        arc_rule = (
            "9. 检查本章是否完成短纲的既定进展，主要阻碍是否有推进或收束，"
            "有无反复提及已退场人物；"
        )
    else:
        antagonist, cast = parse_short_cast(chapter.get("short_characters"))
        count = int(chapter.get("short_chapter_count") or 3)
        start_no = int(chapter.get("short_start_no") or chapter.get("chapter_no") or 1)
        index = int(chapter.get("chapter_no") or start_no) - start_no + 1
        index = max(1, min(index, count))
        brief_block = f"""【本段短纲（覆盖 {count} 章）】
- 本章位置：第 {index}/{count} 章
- 本段开头状态：{chapter.get('short_start_state') or '未提供'}
- 本段最终结果：{chapter.get('short_end_state') or '未提供'}
- 本段已选走向：{chapter.get('plot_choice') or '（未指定，由写手自行决定）'}
- 本段反派：{antagonist or '未指定'}
- 本段人物：{cast or '未指定'}
"""
        outline_rule = (
            "1. 检查正文是否推进本段剧情、是否逐步落到【本段最终结果】，"
            "有无提前写出结果之后的情节、偏离本段已选走向；"
        )
        arc_rule = (
            f"9. 若本章是本段最后一章（第 {count}/{count} 章），检查本段反派或困境是否被解决、退场，"
            "起承转合是否完成，是否把主要冲突整体留给下一段；若不是最后一章，只检查是否有效推进本段冲突、"
            "没有提前解决反派或跳过关键节点；若给出【本段人物】，检查是否使用了名单外角色，以及是否反复提及已退场人物；"
        )

    ai = _invoke_structured(structured_llm, [
        SystemMessage(
            "你是一位小说责任编辑，负责核对正文与细纲、人物设定是否一致。"
            "只依据给定材料判断，不要脑补材料之外的信息。"
        ),
        HumanMessage(content=f"""【所属分卷】
第{chapter['volume_no']}卷《{chapter['volume_title']}》

【所属短纲】
《{chapter['short_title']}》
- 故事走向：{chapter.get('short_storyline')}
- 主要地点：{chapter.get('short_location')}

{brief_block}
【人物档案】
{_person_text(chapter.get("outline_id"))}

【人物关系】
{_relation_text(chapter.get("outline_id"))}

【伏笔清单】
{_foreshadow_text(chapter.get("outline_id"))}

【前文摘要】
{_summary_text(_previous_summaries(chapter))}

【待审正文】
{chapter['content']}

要求：
{outline_rule}
2. 检查人物姓名、性格、能力、关系是否与档案一致，有无凭空新增重要设定；
   但【本段反派】【本段人物】中列出、档案里没有的角色属于短纲授权角色，不算凭空新增，
   只核对其言行是否与短纲中的身份和冲突一致；
3. 检查伏笔是否按计划埋设/揭晓，有无提前泄底或与前文矛盾；
4. 检查正文与前文摘要是否矛盾；
5. 问题要具体到情节或句子，suggestion 给出可执行的修改建议；
6. 检查章内空间与道具逻辑：同一位置或道具是否被两个动作同时占用；关键藏身点是否被搜索，若未被发现须交代合理原因；
7. 若严重偏离主线、人物崩坏或提前泄底，对应维度必须给 60 分以下，
   使加权总分低于 75；
8. 四项评分分别给出 0-100 的整数，只按逻辑一致性打分，不因文笔、措辞扣分：
   细纲符合度（outline_score）、人物一致性（character_score）、
   伏笔处理（foreshadow_score）、前文连贯性（continuity_score）；
   单项完全符合给 90-100，轻微瑕疵 80-89，局部偏离 70-79，
   明显问题 60-69，严重偏离 60 以下；
{arc_rule}
10. 各说明字段控制在 60 字以内，issues 总计不超过 200 字，不要复述原文。""")
    ], ConsistencyResult)

    score, dimension_scores = _weighted_score(ai)
    passed = score >= CONSISTENCY_THRESHOLD
    issues = ai.issues
    if score < CONSISTENCY_THRESHOLD:
        issues = f"一致性加权评分 {score} 低于阈值 {CONSISTENCY_THRESHOLD}；" + (issues or "")

    _save_review(
        "chapter", chapter["id"], "consistency", passed, f"{score}分",
        issues,
        f"细纲符合度：{ai.outline_consistency}（{_score_text(dimension_scores, 'outline')}）；"
        f"人物符合度：{ai.character_consistency}（{_score_text(dimension_scores, 'character')}）；"
        f"伏笔处理：{ai.foreshadow_handling}（{_score_text(dimension_scores, 'foreshadow')}）；"
        f"前文连贯：{ai.continuity_check}（{_score_text(dimension_scores, 'continuity')}）；"
        f"建议：{ai.suggestion}",
        "system",
    )

    return {
        "novel_chapter_id": chapter["id"],
        "passed": passed,
        "score": score,
        "dimension_scores": dimension_scores,
        "weights": CONSISTENCY_WEIGHTS,
        "threshold": CONSISTENCY_THRESHOLD,
        "outline_consistency": ai.outline_consistency,
        "character_consistency": ai.character_consistency,
        "foreshadow_handling": ai.foreshadow_handling,
        "continuity_check": ai.continuity_check,
        "issues": issues,
        "suggestion": ai.suggestion,
    }


def chapterAudit(state: ReviewState):
    """章节审核：一次性执行违规审核与细纲一致性审核"""
    violation = contentViolationCheck(state)
    consistency = contentConsistencyCheck(state)
    return {
        "novel_chapter_id": violation.get("novel_chapter_id"),
        "passed": violation["passed"] and consistency["passed"],
        "violation": violation,
        "consistency": consistency,
    }
