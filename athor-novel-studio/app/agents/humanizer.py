"""去 AI 味润色与审核。

编辑原则来自 Humanizer-zh：
- 保留信息、确定程度与作者声音，不新增事实、数据或经历；
- 只处理空泛铺垫、意义拔高、公式化节奏、套话和聊天腔；
- 模式是检查线索，不是删词表，通顺的句子允许保留。
"""

import re

from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field

from app import monitor
from app.config import settings
from app.llm import create_llm

llm = create_llm(settings.llm_temp_humanizer)
review_llm = create_llm(settings.llm_temp_reviewer)

AI_FLAVOR_THRESHOLD = 90   # 90 分及以上直接通过
MIN_THRESHOLD = 85         # 85-89 为边界区间，需复评或人工确认

POLISH_RULES = """你是一名中文小说润色编辑，任务是把已经写好的章节改得更像作者自然写出的文字，而不是模板文案。

【最高优先级】
1. 只改表达，不改剧情：不新增或删除情节、人物、设定、对话信息，不改变人物关系、因果、时间顺序和结局。
2. 保留确定程度：可能、似乎、据他所知、尚未等限定词不能改成确定判断；“计划”不能写成“已经完成”。
3. 保留作者声音：视角、语气、人物口吻、短句节奏和已有的悬疑感都要保留，不统一改成同一种腔调。

【必须清理的表达】
1. 空转铺垫：删“让我们看看”“接下来将……”“以下是你需要知道的”，直接进入情节。
2. 假对比：删只抬高语气的“不仅是……更是……”，以及先否定再纠正的“不是 X，而是 Y”“不是响。是纸页翻动的声音”，直接写确定的事实。
3. 意义拔高：删“标志着新时代”“彰显了……追求”“开启全新篇章”等句尾或段落赞美。
4. 套话收尾：删“总而言之”“让我们拭目以待”“未来可期”等不提供信息的收束。
5. 客服腔：删“好问题”“希望对你有帮助”“以上就是”等与小说无关的寒暄。
6. 公式化节奏：不硬凑三段式，不堆四字词，不连续用破折号制造悬念，不反复用同一句式开头；清理“眼中闪过一丝……”“一丝不易察觉的笑意”“不由自主地/下意识地”“与其说……不如说”“不知道过了多久”“声音不大，却……”“空气中弥漫着……”“这一刻，他终于明白”等高频套话。
7. 空泛高频词：赋能、闭环、无缝、至关重要、深入探讨等，只在空泛或不准时替换。
8. 复述与重复：不复述章节标题，不把同一意思换词写两遍，不与假想敌辩论。
9. 冗长结构：拆开层叠的长定语，少用“进行＋动词”，被字句堆叠时改主动。
10. 装饰性排版：去掉正文里的表情符号、箭头、分隔线和无意义加粗。
11. 动作无因果：给动作补触发与目的，交代结果；没有“为什么现在做”的动作直接删改。
12. 隐形主语：换主体时补姓名或明确代词，避免读者猜“谁的手”。
13. 主观环境：删“他感到、他觉得、仿佛”，只保留气味、温度、光线、声音等可感知事实。
14. 比喻与叠加（拟人同属此类）：删除所有“像、如同、仿佛、好似、犹如”构成的比喻，改为直接写动作或状态；禁止拟人，风、雨、雾、光、气味、声音、器物不得像人或活物一样自主行动（“腥味追着他”“雾吞了村口”“灯火在低语”），改写为物理状态或人的感受；一个动作只留动静或状态其中一层。
15. 台词与动作不完整：给关键台词补人物、身体动作与说话方式；单字动作与单词台词一律写完整。台词不得电报体或文言式省略，不许只留半句（“力量尽了。这田……也污了。”要展开成“力量已经耗尽了，这亩田也被力量污染了，再也不能种庄稼了。”），主语、谓语与要说清的信息补全，保持人物原本口吻。
16. 镜头硬切：补一个触发动作，或用“见状、闻言、随即、于是”连接，消除生硬切换。
17. 用词规范：替换生造词与冷僻搭配（“旧刀”改“刀”），补全被省略的名词中心词（“响”改“响声”）。
18. 描写逻辑：修正方向、可行性与主语矛盾（“刀横在身前”改“刀身对着院门方向”；“粗哑嗓子又响”改“壮汉大声笑了起来”）。
19. 碎片短句与作者旁白：删掉段末判断句（“但足够”“可已经晚了”），把无主语碎片短句改写成完整动作或事实。
20. 量词与搭配：修正错误量词（“一截泥浆”改“一团泥浆”）与生硬搭配（“火辣辣的痕”改“火辣辣的疼”）。

【改写要求】
- 优先保留原文：只改有问题的句子和段落，原文已经自然的地方原样保留，不要为了改写而改写。
- 审核意见里指出的句子必须逐条处理；不要整章重写，不要改变段落顺序。
- 禁止在改写中引入新的模板腔：排比、四字词堆叠、连续破折号、总结句、拔高句。
- 保持原有段落划分和对话格式，保留原有的伏笔、动作细节、感官描写和章尾钩子。
- 用具体动作、对话和感官细节替代空泛概括，但不凭空补充新细节。
- 只输出润色后的完整正文，不要标题、说明、修改清单或前后缀。
- 字数控制在 2000-3000 字，与原文相差不超过 10%。"""

REVIEW_RULES = """你是一名中文小说的 AI 味审核员。只判断表达是否自然，不判断剧情好坏，不改写正文。

逐项检查：
1. 空转铺垫：是否有只预告下文、不提供信息的句子。
2. 假对比与拔高：“不仅是……更是……”“标志着”“彰显了”等抬高语气的表达；是否出现“不是……，是……”“不是 X，而是 Y”这类先否定再纠正的句式（“不是响。是纸页翻动的声音”），一律判为问题。
3. 套话收尾与客服腔：不提供信息的祝愿、总结、寒暄。
4. 公式化节奏：硬凑三段式、连续同句式开头、堆叠四字词、滥用破折号；是否出现“眼中闪过一丝……”“不由自主地/下意识地”“不知道过了多久”“声音不大，却……”“空气中弥漫着……”“这一刻，他终于明白”等高频套话。
5. 空泛高频词：赋能、闭环、无缝、至关重要等使用是否空泛。
6. 重复：复述标题、同义反复、与假想敌辩论。
7. 冗长：层叠长定语、“进行＋动词”、被字句堆叠。
8. 装饰排版：正文中的 emoji、箭头、分隔线、无意义加粗。
9. 信息边界：是否把“可能”写成“确定”、把计划写成已完成。
10. 作者声音：是否所有段落都像同一种模板腔，缺少人物口吻与节奏变化。
11. 动作因果：动作是否有触发与目的，是否莫名开始或结束、不交代结果。
12. 主语指代：换主体时是否用姓名或明确代词，是否存在“手里多了一条”这类隐形主语。
13. 环境客观：是否用“他感到、他觉得、仿佛”替读者下判断，环境描写是否主观代言。
14. 比喻与叠加（拟人同属此类）：零容忍，凡由“像、如同、仿佛、好似、犹如”构成的比喻一律判严重；同时检查拟人，风、雨、雾、光、气味、声音、器物是否被写成会自主行动的活物（“腥味追着他”“雾吞了村口”“灯火在低语”），以及一个动作是否叠加温度、比喻和情绪判断。
15. 台词与动作不完整：台词是否只有“某某说”、缺少人物与情绪，是否出现单词台词（“退！”）、单字动作（“迈”），是否用电报体或文言式省略把台词砍成半句（“力量尽了。这田……也污了。”）。
16. 镜头硬切：句与句之间是否缺少触发动作或逻辑连接词（见状、闻言、随即、于是）。
17. 用词规范：是否生造词、使用冷僻搭配，或省略名词中心词（“短促的响”应为“短促的响声”）。
18. 描写逻辑：动作方向、可行性与主语是否自洽（刀横在身前却写“刀刃对向声音来处”；“嗓子又响”却无主体）。
19. 碎片短句与作者旁白：段落是否以“但足够”“可已经晚了”“比昨天多了一倍”这类判断句收尾，是否连续使用无主语碎片短句。
20. 量词与搭配：量词是否用错（“一截泥浆”），动宾或修饰搭配是否生硬（“火辣辣的痕”）。

【判定规则（由系统按扣分计算，你不要自己给总分）】
- 共 20 类检查项，每类占 10 分，基准分 100；
- 同一类只取最严重的一条计入扣分：严重扣 10 分，轻微扣 3 分，不重复叠加；
- 任意一条“严重”问题都会导致整章不通过；
- 没有命中的类别不要输出。

【严重程度定义】
- 严重：整段或全篇模板腔；信息边界错误（把可能写成确定、把计划写成已完成）；整章反复出现同一句式；大段空话或拔高影响阅读。
- 轻微：局部一两句模板化，删掉即可，不影响整体阅读。

【输出要求】
- issues 为字符串，每行一条，格式：类别｜严重程度｜原文片段｜修改方向；
- 类别必须使用上面 20 个类别名之一；严重程度只能填“严重”或“轻微”；
- 原文片段不超过 40 字，最多 10 条，按严重程度排序；
- 没有问题时 issues 填“无”；
- suggestion 给出整体修改方向，不改写正文。"""


class AiFlavorResult(BaseModel):
    issues: str = Field(description="问题清单，每行一条：类别｜严重/轻微｜原文片段｜修改方向；无则填“无”")
    suggestion: str = Field(description="整体修改建议，无则填“无”")


def _polish_messages(content: str, issues: str = ""):
    feedback = ""
    if issues and issues.strip() and issues.strip() != "无":
        feedback = f"\n【上一轮 AI 味审核意见，请逐条修正】\n{issues.strip()}\n"
    return [
        SystemMessage(content=POLISH_RULES),
        HumanMessage(content=(
            "请对下面的章节正文做去 AI 味润色，只改表达，不改剧情。\n"
            f"{feedback}\n【原文】\n{content}\n\n"
            "只输出润色后的完整正文，不要标题、说明或修改清单；"
            "字数保持 2000-3000 字，与原文相差不超过 10%。"
        )),
    ]


def _review_messages(content: str):
    return [
        SystemMessage(content=REVIEW_RULES),
        HumanMessage(content=f"请审核下面章节正文的 AI 味，按类别列出命中的问题。\n\n【正文】\n{content}"),
    ]


# 类别归一化：模型可能写成“1. 空转铺垫”或“公式化节奏”等变体
CATEGORY_KEYWORDS = [
    ("不完整", "台词与动作不完整"), ("台词", "台词与动作不完整"),
    ("镜头", "镜头硬切"), ("硬切", "镜头硬切"),
    ("旁白", "碎片短句与作者旁白"), ("碎片", "碎片短句与作者旁白"), ("短句", "碎片短句与作者旁白"),
    ("量词", "量词与搭配"), ("用词", "用词规范"), ("生造", "用词规范"), ("搭配", "用词规范"),
    ("描写逻辑", "描写逻辑"), ("逻辑", "描写逻辑"), ("矛盾", "描写逻辑"),
    ("动作", "动作因果"), ("因果", "动作因果"),
    ("主语", "主语指代"), ("指代", "主语指代"), ("隐形", "主语指代"),
    ("环境", "环境客观"), ("主观", "环境客观"),
    ("比喻", "比喻与叠加"), ("拟人", "比喻与叠加"), ("叠加", "比喻与叠加"), ("猎奇", "比喻与叠加"),
    ("假对比", "假对比与拔高"), ("拔高", "假对比与拔高"),
    ("套话", "套话与客服腔"), ("客服腔", "套话与客服腔"),
    ("公式化", "公式化节奏"), ("节奏", "公式化节奏"),
    ("高频词", "空泛高频词"), ("空泛", "空泛高频词"),
    ("重复", "重复"), ("冗长", "冗长"),
    ("排版", "装饰排版"), ("装饰", "装饰排版"),
    ("信息边界", "信息边界"), ("边界", "信息边界"),
    ("作者声音", "作者声音"), ("模板腔", "作者声音"),
    ("铺垫", "空转铺垫"),
]


def _normalize_category(raw: str) -> str:
    text = raw or ""
    for key, name in CATEGORY_KEYWORDS:
        if key in text:
            return name
    return "其他"


def _parse_issue_lines(raw: str) -> list:
    """把“类别｜严重｜片段｜改法”的文本行解析成结构化问题"""
    items = []
    for line in (raw or "").splitlines():
        line = line.strip().lstrip("-• ").strip()
        if not line or line == "无":
            continue
        parts = [p.strip() for p in re.split(r"[|｜]", line)]
        if len(parts) < 4:
            continue
        items.append({
            "category": _normalize_category(parts[0]),
            "severity": "严重" if "严重" in parts[1] else "轻微",
            "evidence": parts[2],
            "fix": parts[3],
        })
    return items[:10]


def _review_once(content: str) -> dict:
    """单次审核：模型只列问题，分数由扣分规则计算"""
    runnable = review_llm.with_structured_output(AiFlavorResult)
    messages = _review_messages(content)
    ai = None
    for _ in range(2):
        try:
            ai = runnable.invoke(messages)
        except Exception:
            ai = None
        if ai is not None:
            break
    if ai is None:
        # 兜底：改用 DeepSeek JSON 模式再试一次
        try:
            fallback = review_llm.with_structured_output(
                AiFlavorResult, method="json_mode"
            )
            ai = fallback.invoke(messages)
        except Exception:
            ai = None
    if ai is None:
        raise ValueError("AI 味审核未返回结构化结果，请重试")

    # 同一类别只取最严重的一条：严重扣 10，轻微扣 3
    deductions = {}
    issue_list = _parse_issue_lines(ai.issues)
    for item in issue_list:
        cost = 10 if item["severity"] == "严重" else 3
        deductions[item["category"]] = max(
            deductions.get(item["category"], 0), cost
        )

    score = max(0, 100 - sum(deductions.values()))
    return {
        "score": score,
        "vetoed": 10 in deductions.values(),
        "issue_list": issue_list,
        "issues": _format_issues(issue_list),
        "suggestion": ai.suggestion or "无",
    }


def _format_issues(issue_list: list) -> str:
    if not issue_list:
        return "无"
    return "\n".join(
        f"{i + 1}. 【{it['category']}·{it['severity']}】{it['evidence']} → {it['fix']}"
        for i, it in enumerate(issue_list)
    )


def _merge_issues(first: list, second: list) -> list:
    seen, merged = set(), []
    for item in first + second:
        key = (item["category"], item["evidence"])
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return merged


def audit(content: str) -> dict:
    """审核正文 AI 味：分项扣分；85-89 分自动复评一次取平均"""
    first = _review_once(content)
    score = first["score"]
    vetoed = first["vetoed"]
    issue_list = first["issue_list"]
    suggestion = first["suggestion"]
    rechecked = False

    # 边界复评：85-89 分区间再评一次，取平均，降低模型抖动
    if not vetoed and MIN_THRESHOLD <= score < AI_FLAVOR_THRESHOLD:
        rechecked = True
        second = _review_once(content)
        score = round((first["score"] + second["score"]) / 2)
        vetoed = vetoed or second["vetoed"]
        issue_list = _merge_issues(first["issue_list"], second["issue_list"])
        suggestion = second["suggestion"] if second["issue_list"] else suggestion

    passed = (not vetoed) and score >= AI_FLAVOR_THRESHOLD
    return {
        "passed": passed,
        "score": score,
        "threshold": AI_FLAVOR_THRESHOLD,
        "min_threshold": MIN_THRESHOLD,
        "vetoed": vetoed,
        "borderline": (not vetoed) and MIN_THRESHOLD <= score < AI_FLAVOR_THRESHOLD,
        "rechecked": rechecked,
        "issues": _format_issues(issue_list),
        "issue_list": issue_list,
        "suggestion": suggestion,
    }


@monitor.track_step("去AI味润色")
def polish(content: str, issues: str = "") -> str:
    """同步润色一轮，供人工触发的“再润色一轮”使用"""
    ai = llm.invoke(_polish_messages(content, issues))
    return (ai.content or "").strip()


PARAGRAPH_POLISH_RULES = """你是中文小说润色编辑，只能改写给定的一个段落，不输出其他内容。
要求：
1. 只修掉列出的问题，保留原段落全部人名、地名、数字、时间、动作结果、因果与人物关系；
2. 保持叙述视角、人物口吻、段落结尾指向的事件与章末钩子；
3. 不新增情节、不新增人物、不把段落写长或写短（幅度不超过两成）；
4. 只输出改写后的这一段，不要标题、不要解释、不要整体加引号。
硬性禁止（违反任何一条都算失败）：
- 不得出现“像、仿佛、好似、如同、犹如、宛如”中的任何一个字；
- 不得使用拟人，风、雨、雾、光、气味、声音、器物不能有人的动作；
- 不得使用“不是……，是……”“不是……，而是……”这种先否定再纠正的句式，直接写确定的事实；
- 不得写“眼中闪过一丝”“一丝不易察觉的笑意”“不由自主地”“下意识地”“与其说……不如说”“不知道过了多久”“声音不大，却”“空气中弥漫着”“这一刻，他终于明白”。"""


@monitor.track_step("局部去AI味润色")
def polishParagraph(paragraph: str, issues: str = "") -> str:
    """只润色一个问题段落，用于局部去 AI 味"""
    ai = llm.invoke([
        SystemMessage(content=PARAGRAPH_POLISH_RULES),
        HumanMessage(content=(
            f"【本段需要解决的问题】\n{issues or '按去 AI 味规范改得更自然'}\n\n"
            f"【原段落】\n{paragraph}\n\n只输出改写后的这一段。"
        )),
    ])
    return (ai.content or "").strip()


@monitor.track_step("去AI味润色")
async def polishStream(content: str, issues: str = ""):
    """流式输出润色后的正文；调用方负责拼接完整文本"""
    async for chunk in llm.astream(_polish_messages(content, issues)):
        text = chunk.content or ""
        if text:
            yield text
