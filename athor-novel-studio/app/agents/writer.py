from typing import TypedDict

import json
import re
import time

import pymysql
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from app import monitor
from app.config import settings
from app.db import connect as db_connect
from app.llm import create_llm

llm = create_llm(
    settings.llm_temp_writer, presence_penalty=0.45, frequency_penalty=0.3
)
summary_llm = create_llm(settings.llm_temp_summary)


WORLD_LABELS = {
    "spacetime": "所处时空", "rule": "世界规则", "geoEco": "地理生态",
    "history": "既往历史", "populace": "人群分类", "socPower": "权力架构",
    "econLife": "经济日常", "culture": "文化信仰", "powerSys": "能力体系",
}

# 文风规范：依据 3.docx 归纳，写作时必须逐条遵守
WRITING_STYLE_GUIDE = """【文风规范（逐条必须遵守）】
1. 视角：以主角第三人称有限视角为主，只在必要时切入反派或配角视角；切换视角时先用一句话交代是谁在看、身在何处。
2. 段落：一句一段，单段不超过三句，禁止整段堆砌描写，保持移动端阅读的呼吸感。
3. 句式：短句为主，主谓宾直陈；少用长复句、少用排比与华丽辞藻，宁拙勿巧，禁止使用拟人和比喻的修辞手法。
4. 指称：主要人物在关键节点使用全名（如“克林顿·米德尔顿”），日常动作可用“他/她”，同一段内不得称谓混乱。
5. 设定：出现序列、途径、魔药、非凡特性、封印物等术语时，借人物对话或内心独白解释清楚，一段讲透一个概念，禁止长篇设定说明文。
6. 情绪：优先用身体反应与具体念头呈现（手抖、喉紧、呼吸一滞、青筋暴起），必要时才点明情绪；禁止“愤怒燃烧得越来越旺盛”这类抽象形容，也不叠加多层描写。
7. 对话：对话独立成段，口语化且有目的性；反派与高位者要带傲慢、戏谑、说教的口吻，普通人说话要直、要成句，不用电报体。
8. 心理：用短促的内心独白和自问句推进决策（如“怎么办？”“人去哪里了？”），可写“他心里这样想着”。
9. 节奏：用“过了一会”“接着”“随即”“与此同时”“另一边”推进时间与场景；每 500-800 字必须出现一次小转折、新信息或危险升级。
10. 氛围：只写克制的感官细节（光线、气味、声音、温度、触感），反复使用贯穿意象（红月、煤气灯、黑面包、黑焰），营造压抑悬疑。
11. 章尾：结尾必须落在新的危机、反转或未解之谜上，留下明确钩子，不得平淡收束。
12. 用词：保持翻译腔的书面语感，少用成语堆砌；不要模仿原文的口语化错别字（如“自嘲到”“问到”），不使用现代网络流行语。
13. 信息：视角人物不知道的事就不写透，多用“仿佛”“似乎”“好像”保留不确定性；伏笔只推进、不提前揭破。
14. 战斗与追逐：动作拆成短句，按“发现—判断—反应”的顺序写，突出实力差距与灵性消耗，不写无代价的碾压。
15. 不写空转铺垫：禁止“让我们看看”“接下来将”“以下是你需要知道的”，直接进入情节与动作。
16. 不写拔高与宣传：禁止“标志着新时代”“彰显了……追求”“不仅是……更是……”“开启全新篇章”等句式和句尾赞美。
17. 不硬凑三段式、不堆四字词、不滥用破折号；短句直陈，只有真实并列或排比时才使用。
18. 不写客服腔和套话收尾：禁止“希望对你有帮助”“总而言之，让我们拭目以待”。
19. 不复述标题、不重复同一意思、不与假想敌辩论；每段都要推进信息、动作或情绪。
20. 保留不确定性：视角人物不知道的事不写死，不用“显然”“毫无疑问”代替证据；可能、似乎、据他所知等限定要保留。
21. 不复述上一段：每写完一个情绪段落或意象段落，下一段必须包含一个前文未出现过的具体信息（新人物、新物品、新地点或新动作），且不得直接复述上一段的核心词。
22. 动作因果：每个动作必须有触发（闻言、见状、听见）与目的（催促、示警、试探），不得凭空开始或莫名结束，动作结束要交代结果或代价。
23. 主语指代：同一句中换主体必须用姓名或明确代词，禁止“手里多了一条短索”这类隐形主语；跨句承接时先写触发词再写动作。
24. 环境客观：只写可感知的事实（气味、温度、光线、声音），删掉“他感到、他觉得、仿佛”，不替读者下情绪判断。
25. 比喻与叠加：全文禁用比喻，不得使用“像、如同、仿佛、好似、犹如”等构成的明喻，也不得用比喻替代动作（“皮肤下像有一小团火在跳”改为“胸口那包稻种一下一下发烫”）；一个动作只写动静，不叠加温度与情绪判断。固定成语和惯用语（如“像模像样”）除外。“谁＋做什么＋怎么说”属于一个完整动作，不算叠加。
26. 设定信息：世界观术语必须随角色当下的判断或选择带出，用“他想起、他判断”的视角句，避免“A 是……B 是……”的说明文和“周伯说过：”式口语复述。
27. 台词逻辑：每句台词都要有当下的动机与对象，删除重复铺垫与总结式台词；前文已进入冲突时，不得再出现“我再说一遍”这类与前文矛盾的台词。
28. 动词精度：用具体、可被看见的动词，避免“发抖、愣了一下、笑了笑、点了点头”等泛化动作词，按质感择词（如“颤抖”优于“发抖”）。
29. 镜头桥接：两个动作之间若无天然因果，必须用一个突然的动作、声音或反应衔接（“呀了一声→站起来→能动”），禁止用句号硬切镜头。
30. 动作写全：关键台词不能只写“某某说”，至少补身体动作与说话方式（“睥睨着赵福，冷冷地说道”）；“谁＋做什么＋怎么说”算一个完整动作，不算叠加。
31. 动作有目的：回头、停步、抬手等动作后面必须接“为了什么”，没有目的的动作删除或补足。
32. 句间逻辑：用“见状、闻言、随即、于是、这才”显式标出因果与先后，禁止把动作写成互不相干的清单。
33. 用词规范：不生造词、不用冷僻搭配（“旧刀”写“刀”），名词不省略中心词（“短促的响”写“短促的响声”），优先使用大众熟知的说法。
34. 描写逻辑：每句自检方向、可行性与主语——动作与朝向必须一致（“刀横在身前”就不能“刀刃对向声音来处”），主语必须能发出该动作（“嗓子又响”改为“壮汉大声笑了起来”）。
35. 动作写完整：禁止单字动作（“迈”写“踏进去”），动词要带方向或对象，避免没有后续的孤立动作。
36. 台词写完整：禁止单词台词（“退！”写“这里有问题，快后退！”）；每句台词前交代“人物＋动作或情绪”，说话动词用“问道、说道、喊道”，禁止“有人喊”“粗哑嗓子说”。叙述可以短，台词必须成句：禁止电报体、文言式省略和只留半句（“力量尽了。这田……也污了。”写“力量已经耗尽了，这亩田也被力量污染了，再也不能种庄稼了。”），主语、谓语和信息都要交代完整。
37. 禁止旁白判断：段落不得以作者评价或总结收尾，删掉“很淡。但足够。”“可已经晚了。”“比昨天多了一倍。”这类判断句，只保留可观察的事实与动作。
38. 设定讲解：设定信息必须拆散在动作、判断与场景中，单次对白最多交代两条设定，禁止器灵或配角连续口述规则。
39. 禁用拟人：不得让风、雨、雾、光、气味、声音、器物像人或活物一样自主行动（“腥味追着他”“雾吞了村口”“灯火在低语”“月光爬上墙”），一律改写成可观察的物理状态或人的真实感受（“腥味从沟里飘上来，越来越浓”“雾漫过田埂”“灯光照在墙上”）。
40. 禁用「不是……，是……」句式：禁止先否定再纠正的对照写法，包括“不是响。是纸页翻动的声音”“不是害怕，而是不甘”“不是没人管，是管不了”。直接写确定的那个事实，例如改成“纸页翻动的声音”“他心里不甘，却不肯退”“没人管这件事”。
41. 禁用高频 AI 套话：不得写“眼中闪过一丝……”“一丝不易察觉的笑意”“不由自主地/下意识地”“与其说……不如说……”“不知道过了多久”“声音不大，却……”“空气中弥漫着……”“这一刻，他终于明白”。改用具体动作、可观察的细节或直接陈述。

【正反示例（写作时逐条对照）】
✗ 白净弟子朝同伴偏了偏头。 → ✓ 白净弟子朝同伴偏了偏头，催促道。
✗ 另一个灰袍弟子绕到板车左侧，手里多了一条赤色短索。 → ✓ 闻言，另一个灰袍弟子绕到板车左侧，他的手里不知何时多了一条赤色短索。
✗ 他闻到的气味更浓了，那股酸苦味从车上漫下来。 → ✓ 烧焦灵药混着虫壳的酸苦味越来越浓。
✗ 古印贴着皮肤跳得像颗活物；他心里愤怒燃烧得越来越旺盛。 → ✓ 古印一下一下顶着他的腰，似乎变得越来越活跃。
✗ 周伯说过，灵矿残渣分两种：死渣和活渣。死渣是…… → ✓ 他盯着渣块想：活渣还封着半口灵气，死渣一碰就碎。
✗ “力量尽了。这田……也污了。” → ✓ “力量已经耗尽了，这亩田也被力量污染了，再也不能种庄稼了。”
✗ 一股腥味追着他。 → ✓ 腥味从沟里飘上来，越来越浓。
✗ 前文已动手，却说“我再说一遍”。 → ✓ “把车留下，人跟我们走。”

【动作写作正反示例（逐条对照）】
✗ 赵福声音发抖。 → ✓ 赵福声音颤抖。
✗ 青白雾气缓缓退去，赵福的腿慢慢能动了。 → ✓ 青白雾气缓缓退去。赵福呀了一声，居然站了起来，能动了。
✗ “这田，他买不走。”沈青说。 → ✓ “这田，他买不走。”沈青睥睨着赵福，冷冷地说道。
✗ 他翻到一半，又回头。 → ✓ 他翻到一半，又回头，提醒道：“沈家小子，你斗不过员外的。”
✗ 沈青没应声。赵福跳下墙，脚步声很快消失在土路尽头。 → ✓ 沈青没应声。见状，赵福摇了摇头，随即跳下墙，脚步声很快消失在土路尽头。

【用词与逻辑正反示例（逐条对照）】
✗ 沈青把旧刀横在身前，刀刃对向声音来处。 → ✓ 沈青把刀横在身前，刀身对着院门方向。
✗ 皮肤下像有一小团火在跳。 → ✓ 胸口那包稻种一下一下发烫。
✗ 发出短促的响。 → ✓ 发出短促的响声。
✗ “沈家小子！”粗哑嗓子又响起来。 → ✓ “沈家小子！”追来的壮汉大声笑了起来。
✗ 抬脚又往田里迈。 → ✓ 抬脚又往田里踏进去。
✗ “退！” → ✓ “这里有问题，快后退！”
✗ “邪术！”有人喊。 → ✓ “邪术！”最前面的私兵后退半步，喊道。
✗ “赵福没回去？”他扬声问。 → ✓ “赵福没回去？”他扬声问道。
✗ 很淡。但足够。 → ✓ 稻香从田里漫过来，只有淡淡一层。
✗ 可已经晚了。 → ✓ 三个人的脚踝已经缠在一起。
✗ “灵稻香会散出去……禁制就能粘住。可你只有一次机会。” → ✓ 器灵只说了半句：“香一散，他们就会进来。”他顿了顿，“只有一次机会。”"""

METAPHOR_PATTERN = re.compile(r"像|仿佛|好似|如同|犹如|宛如|恍如|恍若")
METAPHOR_ALLOW = (
    "像模像样", "像样", "不像话", "好像", "画像", "图像", "肖像", "偶像",
    "影像", "录像", "佛像", "雕像", "石像", "塑像", "头像", "相像", "想像",
)


def find_metaphor_hits(text: str) -> list[str]:
    """扫描正文中的比喻句（明喻标记），命中则返回原句，用于强制重写"""
    hits = []
    for line in (text or "").splitlines():
        cleaned = line
        for word in METAPHOR_ALLOW:
            cleaned = cleaned.replace(word, "")
        if METAPHOR_PATTERN.search(cleaned):
            hits.append(line.strip()[:60])
    return hits


DIALOGUE_TAG_PATTERN = re.compile(r"(?<![道劝解演学游小听再虽就也据])说(?=[，。：”])")
BAD_SPEAKER_PATTERN = re.compile(r"有(?:人|个)[^，。]{0,3}(?:喊|说|叫)(?![法话明])")


def find_dialogue_tag_hits(text: str) -> list[str]:
    """扫描不合格的说话标记：单用“说”作提示语、“有人喊”等无主体表达"""
    hits = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or "”" not in s:
            continue
        # 先去掉引号内的台词，只在引号外查提示语，避免误伤台词里的“说”
        outside = re.sub(r"“[^”]*”", "", s)
        if DIALOGUE_TAG_PATTERN.search(outside) or BAD_SPEAKER_PATTERN.search(outside):
            hits.append(s[:60])
    return hits


STYLE_PATTERNS = [
    re.compile(r"一截一截"),                                        # 量词叠用
    re.compile(r"一截(泥浆|泥水|血|血水|雾气|雾|光|月光|影子|声音|气味|风)"),
    re.compile(r"火辣辣的(痕|感觉|触感)"),                          # 搭配生硬
    re.compile(r"(很|太|极)(淡|轻|静|冷|暗|短)。但"),                # 旁白判断：很淡。但足够。
    re.compile(r"可(他|她|他们|众人)?没有(停|回头|应声|犹豫)。"),     # 旁白判断：可他没有停。
    re.compile(r"可已经(晚了|来不及了|迟了)。"),
    re.compile(r"(气|香|烟|臭|腥|焦糊)味[^，。]{0,10}(追(?!(?:了)?(?:过去|过来|进|入|上|出|到))|缠|跟着|扑(?![鼻面来]))"),  # 拟人生硬
    # 明确拟人：风雨雾光、气味声音做“低语、叹息、舔、咬、吞”这类只有活物才有的动作
    re.compile(
        r"(风|雨|雨声|风声|雪|雾|云|光|月光|灯光|灯火|影子|气味|香气|腥味|声音)"
        r"(?:在|正)?(低语|叹息|呢喃|咆哮|舔|咬|吞)"
    ),
    # 高频 AI 套话与公式化句式，沉淀为确定性规则
    re.compile(r"(眼中|眼里|眼底|眸中|心底|心中)(闪过|掠过|涌起|泛起)(一丝|一抹|一缕)"),
    re.compile(r"(一丝|一抹|一缕)(不易察觉的)?(笑意|冷笑|暖意|寒意|不安|担忧|希望|失望|杀意|犹豫)"),
    re.compile(r"不由自主地|下意识地|情不自禁地"),
    re.compile(r"与其说[^。！？]{1,30}不如说"),
    re.compile(r"不知道过了多久"),
    re.compile(r"(声音|语气|嗓音)(不大|不高|很轻|平静)，却"),
    re.compile(r"空气(中)?(仿佛|似乎)?(弥漫|凝固|安静|安静下来)"),
    re.compile(r"这一刻[，,]?(他|她|所有人)?(终于)?(明白|懂了|意识到)"),
    re.compile(r"(眼底|眼中)(深处)?(闪过|掠过)"),
]


def find_style_hits(text: str) -> list[str]:
    """扫描量词误用、旁白判断、拟人生硬等确定性文风硬伤"""
    hits = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s and any(p.search(s) for p in STYLE_PATTERNS):
            hits.append(s[:60])
    return hits


# 「不是……，是……」先否定再纠正的对照句式，零容忍
CONTRAST_PATTERN = re.compile(r"不是[^。！？\n]{0,60}?(?:。|，|,|；|;)\s*(?:而)?是")


def find_contrast_hits(text: str) -> list[str]:
    """扫描「不是……，是……」句式，命中则返回原句，用于强制重写"""
    hits = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s and CONTRAST_PATTERN.search(s):
            hits.append(s[:60])
    return hits


def line_issues(line: str) -> list[str]:
    """返回单个段落命中的确定性问题，供局部改写定位"""
    s = (line or "").strip()
    if not s:
        return []
    issues = []
    if find_contrast_hits(s):
        issues.append("「不是……，是……」先否定再纠正句式")
    if find_metaphor_hits(s):
        issues.append("比喻（像/仿佛/好似/如同/犹如）")
    if find_dialogue_tag_hits(s):
        issues.append("说话提示语单用“说”或缺少主体")
    if find_style_hits(s):
        issues.append("AI 套话、旁白判断或生硬搭配")
    return issues


def locality_targets(text: str) -> list[dict]:
    """按段落定位问题句，供局部重写与局部润色使用"""
    targets = []
    for index, line in enumerate((text or "").split("\n")):
        issues = line_issues(line)
        if issues:
            targets.append({"index": index, "text": line, "issues": issues})
    return targets


PARAGRAPH_REWRITE_RULES = """你是中文小说写手，只能重写给定的一个段落。
要求：
1. 只解决列出的问题，段落之外的内容一个字都不要输出；
2. 保留原段落全部人名、地名、数字、时间、动作结果、因果和人物关系；
3. 保持与上下文的衔接、叙述视角和人物口吻；
4. 不新增情节、不新增人物、不改变段落结尾指向的事件；
5. 直接输出改写后的这一段，不要解释、不要标题、不要整体加引号。
硬性禁止（违反任何一条都算失败）：
- 不得出现“像、仿佛、好似、如同、犹如、宛如”中的任何一个字；
- 不得使用拟人，风、雨、雾、光、气味、声音、器物不能有人的动作；
- 不得使用“不是……，是……”“不是……，而是……”这种先否定再纠正的句式，直接写确定的事实；
- 不得写“眼中闪过一丝”“一丝不易察觉的笑意”“不由自主地”“下意识地”“与其说……不如说”“不知道过了多久”“声音不大，却”“空气中弥漫着”“这一刻，他终于明白”。"""


@monitor.track_step("局部重写")
def rewriteParagraph(paragraph: str, issues: str = "") -> str:
    """只重写一个问题段落，用于审核不通过时的局部修复"""
    ai = llm.invoke([
        SystemMessage(content=PARAGRAPH_REWRITE_RULES),
        HumanMessage(content=(
            f"【本段需要解决的问题】\n{issues or '按文风规范改得更自然'}\n\n"
            f"【原段落】\n{paragraph}\n\n只输出改写后的这一段。"
        )),
    ])
    return (ai.content or "").strip()


class WriterState(TypedDict):
    userinput: str
    chapter_outline_id: int
    novel_chapter_id: int
    outline_id: int
    content: str
    summary: str
    audit_issues: str
    resume: bool
    scene_choice: str


class PersonState(BaseModel):
    name: str = Field(description="人物姓名，必须与人物档案一致")
    state: str = Field(description="本章结束时的状态：伤势、境界、知情、立场等，无变化填“无”")
    location: str = Field(default="", description="本章结束时所在地点，未知填空")


class ForeshadowUpdate(BaseModel):
    name: str = Field(description="伏笔名称，必须与伏笔清单一致")
    action: str = Field(description="本章对该伏笔的动作：埋设 / 推进 / 回收")
    note: str = Field(default="", description="一句话说明本章如何处置该伏笔")


class ChapterSummary(BaseModel):
    summary: str = Field(
        description="剧情梗概：100-150字，最多4句，只写主角关键行动与结果，不写细节和修饰"
    )
    key_points: str = Field(description="关键情节点，用分号分隔，按先后顺序")
    characters: str = Field(description="本章出场人物及其在本章中的状态变化")
    foreshadow: str = Field(description="本章涉及的伏笔及其推进情况，无则填“无”")
    next_hook: str = Field(description="本章结尾留下的悬念或下一章需要接续的点")
    person_states: list[PersonState] = Field(
        default_factory=list, description="本章结束时人物状态有变化的人物，未变化的不列"
    )
    foreshadow_updates: list[ForeshadowUpdate] = Field(
        default_factory=list, description="本章埋设、推进或回收的伏笔，没有则返回空列表"
    )


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


# ------------------------------- 上下文组装 -------------------------------

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


def _word_count(text: str) -> int:
    """正文有效字数：去掉空白后的字符数，与页面展示保持一致"""
    return len(re.sub(r"\s+", "", text or ""))


def _person_text(volume_no=None, focus_names=None, outline_id=None):
    fields = (
        "name, age, gender, appear, charTr, situat, ability, goal, "
        "current_state, current_location"
    )
    conds, args = [], []
    if outline_id:
        conds.append("outline_id = %s")
        args.append(outline_id)
    if volume_no:
        conds.append("(first_volume_no IS NULL OR first_volume_no <= %s)")
        args.append(volume_no)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    rows = _fetch_all(
        f"SELECT {fields} FROM person{where} ORDER BY name", tuple(args)
    )
    if not rows:
        return "（暂无人物记录）"

    focus_names = focus_names or ""
    full_lines = []
    brief_lines = []
    for r in rows:
        line = (
            f"- {r['name']}（{r.get('gender') or '未知'}，{r.get('age') or '?'}岁）："
            f"外貌 {r.get('appear') or '未知'}；性格 {r.get('charTr') or '未知'}；"
            f"处境 {r.get('situat') or '未知'}；能力 {r.get('ability') or '未知'}；"
            f"目标 {r.get('goal') or '未知'}"
        )
        if r.get("current_state"):
            line += f"；截至上一章状态：{r['current_state']}"
        if r.get("current_location"):
            line += f"；所在地点：{r['current_location']}"
        if not focus_names or r["name"] in focus_names:
            full_lines.append(line)
        else:
            brief_lines.append(
                f"- {r['name']}：{r.get('situat') or '本卷相关角色'}"
                + (f"；当前状态：{r['current_state']}" if r.get("current_state") else "")
            )

    parts = list(full_lines)
    if brief_lines:
        parts.append("其他本卷可出场人物（简略）：")
        parts.extend(brief_lines)
    return "\n".join(parts)


def _relation_text(volume_no=None, outline_id=None):
    if outline_id:
        # 关系表自身已带 outline_id，直接按书取，避免同名人物 JOIN 出重复
        rows = _fetch_all(
            "SELECT name_a, name_b, relation_desc, relation_type "
            "FROM person_relation WHERE outline_id = %s",
            (outline_id,),
        )
    elif volume_no:
        rows = _fetch_all(
            "SELECT pr.name_a, pr.name_b, pr.relation_desc, pr.relation_type "
            "FROM person_relation pr "
            "JOIN person pa ON pa.id = pr.person_id_a "
            "JOIN person pb ON pb.id = pr.person_id_b "
            "WHERE (pa.first_volume_no IS NULL OR pa.first_volume_no <= %s) "
            "  AND (pb.first_volume_no IS NULL OR pb.first_volume_no <= %s)",
            (volume_no, volume_no),
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
    where = "WHERE status IS NULL OR status <> '已回收'"
    args = ()
    if outline_id:
        where += " AND outline_id = %s"
        args = (outline_id,)
    rows = _fetch_all(
        "SELECT name, content, plant_place, reveal_place, importance, status "
        f"FROM foreshadow {where} "
        "ORDER BY FIELD(importance, '核心', '主线', '支线'), id "
        "LIMIT 12",
        args,
    )
    if not rows:
        return "（暂无伏笔记录）"
    return "\n".join(
        f"- {r['name']}【{r.get('importance') or '支线'}·{r.get('status') or '未回收'}】："
        f"{r.get('content')}；埋设于 {r.get('plant_place')}；揭晓于 {r.get('reveal_place')}"
        for r in rows
    )


CHAPTER_SQL = """
SELECT co.*, so.seq AS short_seq, so.title AS short_title,
       so.storyline AS short_storyline, so.location AS short_location,
       so.start_state AS short_start_state, so.end_state AS short_end_state,
       so.chapter_count AS short_chapter_count, so.segment_mode,
       so.characters AS short_characters,
       so.plot_choice_mode, so.plot_choice_no, so.plot_choice, so.plot_options,
       (SELECT MIN(c2.chapter_no) FROM chapter_outline c2
        WHERE c2.short_id = co.short_id) AS short_start_no,
       v.volume_no, v.title AS volume_title, v.outline_id
FROM chapter_outline co
JOIN short_outline so ON co.short_id = so.id
JOIN volume v ON so.volume_id = v.id
"""


def _segment_info(chapter):
    """返回当前章在短纲段落中的位置：第几章 / 共几章"""
    start_no = chapter.get("short_start_no") or chapter.get("chapter_no") or 1
    count = int(chapter.get("short_chapter_count") or 3)
    index = int(chapter.get("chapter_no") or 1) - int(start_no) + 1
    return max(1, min(index, count)), count


def parse_short_cast(characters):
    """从短纲 characters 字段拆出（本段反派, 本段人物）"""
    text = (characters or "").strip()
    m = re.match(r"反派[:：]\s*(.*?)[；;]\s*本段人物[:：]\s*(.*)", text, re.S)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", text


def _chapter_row(chapter_outline_id):
    return _fetch_one(CHAPTER_SQL + " WHERE co.id = %s", (chapter_outline_id,))


def _next_chapter_row(outline_id=None):
    """按 卷 → 短纲 → 章 的顺序，取第一条尚未成文的章纲"""
    sql = CHAPTER_SQL + """
        LEFT JOIN novel_chapter nc ON nc.chapter_outline_id = co.id
        WHERE nc.id IS NULL
    """
    args = []
    if outline_id:
        sql += " AND v.outline_id = %s"
        args.append(outline_id)
    sql += " ORDER BY v.volume_no, so.seq, co.chapter_no LIMIT 1"
    return _fetch_one(sql, tuple(args))


def _previous_summaries(volume_no, short_seq, chapter_no, outline_id=None, limit=2):
    """取当前章之前、已生成摘要的若干章，按时间正序返回"""
    where = "WHERE (v.volume_no, so.seq, co.chapter_no) < (%s, %s, %s)"
    args = [volume_no, short_seq, chapter_no]
    if outline_id:
        where += " AND v.outline_id = %s"
        args.append(outline_id)
    args.append(limit)
    rows = _fetch_all(
        """
        SELECT nc.chapter_no, nc.title, nc.summary
        FROM novel_chapter nc
        JOIN chapter_outline co ON nc.chapter_outline_id = co.id
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        """ + where + """
          AND nc.summary IS NOT NULL AND nc.summary <> ''
        ORDER BY v.volume_no DESC, so.seq DESC, co.chapter_no DESC
        LIMIT %s
        """,
        tuple(args)
    )
    return list(reversed(rows))


def _volume_recap(volume_no, short_seq, chapter_no, outline_id=None):
    """本卷已写章节的滚动摘要，提供卷内长线上下文"""
    where = "WHERE v.volume_no = %s AND (so.seq, co.chapter_no) < (%s, %s)"
    args = [volume_no, short_seq, chapter_no]
    if outline_id:
        where += " AND v.outline_id = %s"
        args.append(outline_id)
    rows = _fetch_all(
        """
        SELECT nc.chapter_no, nc.summary
        FROM novel_chapter nc
        JOIN chapter_outline co ON nc.chapter_outline_id = co.id
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        """ + where + """
          AND nc.summary IS NOT NULL AND nc.summary <> ''
        ORDER BY so.seq, co.chapter_no
        """,
        tuple(args),
    )
    if not rows:
        return ""
    text = "\n".join(f"第{r['chapter_no']}章：{r['summary']}" for r in rows)
    return text[-1200:]


def _previous_ending(volume_no, short_seq, chapter_no, outline_id=None):
    """取上一章正文的结尾片段，用于保持语感与情节衔接"""
    where = "WHERE (v.volume_no, so.seq, co.chapter_no) < (%s, %s, %s)"
    args = [volume_no, short_seq, chapter_no]
    if outline_id:
        where += " AND v.outline_id = %s"
        args.append(outline_id)
    row = _fetch_one(
        """
        SELECT nc.title, nc.content
        FROM novel_chapter nc
        JOIN chapter_outline co ON nc.chapter_outline_id = co.id
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        """ + where + """
        ORDER BY v.volume_no DESC, so.seq DESC, co.chapter_no DESC
        LIMIT 1
        """,
        tuple(args)
    )
    if not row or not row.get("content"):
        return "（这是开篇章节，无前文）"
    content = row["content"].strip()
    return f"《{row['title']}》结尾：\n{content[-800:]}"


def _summary_text(summaries):
    if not summaries:
        return "（暂无前文摘要）"
    return "\n\n".join(
        f"【第{s['chapter_no']}章《{s['title']}》】\n{s['summary']}"
        for s in summaries
    )


# ------------------------------- 小说写手 -------------------------------

def _draft_chapter_row(outline_id=None, chapter_outline_id=None):
    """取未完成的草稿章节，用于断点续写；可按大纲或章纲限定范围"""
    sql = """
        SELECT co.*, so.seq AS short_seq, so.title AS short_title,
               so.storyline AS short_storyline, so.location AS short_location,
               so.start_state AS short_start_state, so.end_state AS short_end_state,
               so.chapter_count AS short_chapter_count, so.segment_mode,
               so.characters AS short_characters,
               so.plot_choice_mode, so.plot_choice_no, so.plot_choice, so.plot_options,
               (SELECT MIN(c2.chapter_no) FROM chapter_outline c2
                WHERE c2.short_id = co.short_id) AS short_start_no,
               v.volume_no, v.title AS volume_title, v.outline_id,
               nc.content AS draft_content, nc.word_count AS draft_words
        FROM chapter_outline co
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        JOIN novel_chapter nc ON nc.chapter_outline_id = co.id
        WHERE nc.status = '草稿'
          AND nc.content IS NOT NULL AND nc.content <> ''
    """
    args = []
    if outline_id:
        sql += " AND v.outline_id = %s"
        args.append(outline_id)
    if chapter_outline_id:
        sql += " AND co.id = %s"
        args.append(chapter_outline_id)
    sql += " ORDER BY nc.id DESC LIMIT 1"
    return _fetch_one(sql, tuple(args))


def _can_snapshot(chapter_outline_id):
    """只有本章还没有正式正文时才允许把中断内容存成草稿，避免覆盖已完成稿"""
    row = _fetch_one(
        "SELECT status FROM novel_chapter WHERE chapter_outline_id = %s",
        (chapter_outline_id,),
    )
    return not row or row.get("status") == "草稿"


def _select_chapter(state: WriterState):
    if state.get("resume"):
        chapter = _draft_chapter_row(
            chapter_outline_id=state.get("chapter_outline_id")
        )
        if not chapter:
            raise ValueError("没有可续写的草稿")
        return chapter
    chapter_outline_id = state.get("chapter_outline_id")
    if chapter_outline_id:
        chapter = _chapter_row(chapter_outline_id)
        if not chapter:
            raise ValueError(f"chapter_outline 表中不存在 id={chapter_outline_id} 的章纲")
        return chapter
    chapter = _next_chapter_row(outline_id=state.get("outline_id"))
    if not chapter:
        raise ValueError("当前会话没有可续写的章纲，请先生成本会话的大纲与结构")
    return chapter


def _is_legacy(chapter):
    """是否使用旧的逐章细纲模式（新短纲段落由 segment_mode 标记）"""
    if int(chapter.get("segment_mode") or 0):
        return False
    return bool((chapter.get("summary") or "").strip())


def _writer_messages(
    chapter, summaries, ending, audit_issues, target_words,
    draft_text="", scene_choice="",
):
    feedback_block = ""
    if audit_issues:
        feedback_block = (
            "【上一轮审核意见，必须逐条修正】\n"
            f"{audit_issues}\n\n"
            "注意：重写仍须严格遵循本章章纲与世界观，不得为规避审核意见而偏离剧情。\n"
        )

    draft_block = ""
    if draft_text:
        draft_block = (
            "【已写草稿（只作为前文，不要重复）】\n"
            f"{draft_text[-1500:]}\n\n"
            "本次只输出从草稿末尾继续写的新内容：不要复述已有段落，不要重新开头，"
            "直接从断点往下写，并补足到目标字数。\n"
        )

    recap = _volume_recap(
        chapter["volume_no"], chapter["short_seq"], chapter["chapter_no"],
        chapter.get("outline_id"),
    )
    recap_block = f"【本卷前情（滚动摘要）】\n{recap}\n\n" if recap else ""

    # 章纲有剧情梗概 = 旧模式（逐章细纲）；否则走短纲模式（3 章一段，控开头与结局）
    legacy = _is_legacy(chapter)

    scene_block = ""
    if scene_choice:
        scene_block = (
            "【本章采用的场景走向（只写这一条）】\n"
            f"{scene_choice}\n\n"
            "要求：整章必须围绕该走向展开，不得改写成其他走向，也不得把三条走向混在一起。\n"
        )
    elif not legacy:
        plot_choice = (chapter.get("plot_choice") or "").strip()
        if plot_choice:
            scene_block = (
                "【本段已选故事走向（必须遵守）】\n"
                f"{plot_choice}\n\n"
                "要求：这一段三章都按该走向推进，本章不得改写成其他走向。\n"
            )
        elif (chapter.get("plot_choice_mode") or "") == "auto":
            scene_block = (
                "【本段故事走向：由你自行处理】\n"
                "作者未指定走向，请依据本段开头状态与最终结果，自行确定一条合理的"
                "发展路径，并保持这一走向贯穿本段三章，不要中途改向。\n"
            )

    if legacy:
        chapter_block = f"""【本章章纲】
- 章节序号：{chapter.get('chapter_no')}
- 章节名：{chapter.get('title')}
- 剧情梗概：{chapter.get('summary')}
- 写作目的：{chapter.get('purpose')}
- 场景：{chapter.get('scene')}
- 出场人物：{chapter.get('characters')}
- 本章冲突：{chapter.get('conflict')}
- 章尾钩子：{chapter.get('ending_hook')}
- 建议字数：{target_words}
"""
        rule_block = f"""写作要求：
1. 严格按章纲写，不新增章纲之外的主线情节，可补充合理的细节与对话；
2. 人物言行必须符合人物档案与关系，姓名不得随意更改；
3. 涉及伏笔时按清单中的埋设/揭晓安排自然推进，不要提前揭破；本章最多推进 1-2 条伏笔，不得回收尚未到揭晓位置的伏笔；
4. 承接上一章结尾，开头几句话要把读者带回场景；
5. 结尾必须落在章纲给出的钩子上；
6. 正文必须 2000-3000 字：不得少于 2000 字，不得超过 3000 字（以 {target_words} 字为目标）；
7. 严格遵循章纲给出的场景地点，不得擅自把故事拉回初始地点；涉及迁移时，要写出环境、势力与氛围的变化；
8. 必须逐条落实【文风规范】的 41 条款，段落、句式、对话、心理、节奏与章尾钩子均按该规范执行；
9. 不要用空泛铺垫、意义拔高、套话收尾和客服腔凑字数，写完后应像作者自然写出的章节；
10. 若给出【本章采用的场景走向】，必须严格按该走向写，不得临时改成别的走向。"""
    else:
        seg_index, seg_count = _segment_info(chapter)
        if seg_index <= 1:
            position_rule = (
                "本章是本段第 1 章：从【本段开头状态】起笔，交代当下的处境与矛盾，"
                "把人物推进到本段的主要冲突中，不要提前写出【本段最终结果】。"
            )
        elif seg_index >= seg_count:
            position_rule = (
                f"本章是本段第 {seg_index}/{seg_count} 章，也是本段最后一章："
                "必须把故事推进到【本段最终结果】，写清结果与代价，并留下通往下一段的钩子。"
            )
        else:
            position_rule = (
                f"本章是本段第 {seg_index}/{seg_count} 章：承接前一章继续推进冲突，"
                "让局势向【本段最终结果】靠近，但不要提前收束。"
            )
        antagonist, cast = parse_short_cast(chapter.get("short_characters"))
        chapter_block = f"""【本章所属短纲（第 {seg_index}/{seg_count} 章）】
《{chapter.get('short_title')}》
- 本段开头状态：{chapter.get('short_start_state') or '（未提供，按上一章结尾自然承接）'}
- 本段最终结果：{chapter.get('short_end_state') or '（未提供，按故事走向合理收束）'}
- 本段故事线：{chapter.get('short_storyline')}
- 本段反派：{antagonist or '（未指定，按故事线判断本段主要阻碍）'}
- 本段人物：{cast or '（未指定）'}
- 主要地点：{chapter.get('short_location')}
- 章节序号：{chapter.get('chapter_no')}
- 建议字数：{target_words}

【本段位置与任务】
{position_rule}
"""
        rule_block = f"""写作要求：
1. 只写本段短纲覆盖的内容，不得提前写出【本段最终结果】之后的情节；
2. 人物言行必须符合人物档案与关系，姓名不得随意更改；
3. 涉及伏笔时按清单中的埋设/揭晓安排自然推进，不要提前揭破；本章最多推进 1-2 条伏笔；
4. 承接上一章结尾，开头几句话要把读者带回场景；
5. 正文第一行只输出章节标题，格式为「标题：xxx」；标题 6-12 字，有画面或悬念，不带“第X章”，随后换行再写正文；
6. 正文必须 2000-3000 字：不得少于 2000 字，不得超过 3000 字（以 {target_words} 字为目标）；
7. 严格遵循本段主要地点，不得擅自把故事拉回初始地点；涉及迁移时，要写出环境、势力与氛围的变化；
8. 必须逐条落实【文风规范】的 41 条款，段落、句式、对话、心理、节奏与章尾钩子均按该规范执行；
9. 不要用空泛铺垫、意义拔高、套话收尾和客服腔凑字数，写完后应像作者自然写出的章节；
10. 若给出【本段已选故事走向】，必须严格按该走向写，不得临时改成别的方向；
11. 本章只使用【本段人物】中的角色；未列出的旧人物不得出场，已退场的人物最多用一句回忆带过，不得反复提及；本段反派若不在人物档案中，以【本段反派】的设定为准，不得改名或另编背景；
12. 本段三章要讲完一个完整故事：第 1 章起、第 2 章承、本章转合；第 3 章必须解决本段反派或困境，不得把主要冲突留给下一段。"""

    return [
        SystemMessage(
            "你是一位小说写手，擅长依据章纲或短纲把故事写成有画面感、有情绪张力的正文。"
            "你必须严格遵循世界观设定、人物档案与既有伏笔，不得擅自改动主线走向，"
            "并且必须逐条遵守给定的【文风规范】，文风一致性优先于个人表达习惯。"
        ),
        HumanMessage(content=f"""【世界观】
{_worldview_text(chapter.get("outline_id"))}

【人物档案】
{_person_text(chapter.get("volume_no"), chapter.get("characters") or "", chapter.get("outline_id"))}

【人物关系】
{_relation_text(chapter.get("volume_no"), chapter.get("outline_id"))}

【伏笔清单】
{_foreshadow_text(chapter.get("outline_id"))}

【本章所在分卷】
第{chapter['volume_no']}卷《{chapter['volume_title']}》

【本章所属短纲】
《{chapter['short_title']}》
- 故事走向：{chapter.get('short_storyline')}
- 主要地点：{chapter.get('short_location')}

{chapter_block}
{scene_block}{recap_block}【前文摘要】
{_summary_text(summaries)}

【上一章结尾】
{ending}

{draft_block}{WRITING_STYLE_GUIDE}

{feedback_block}{rule_block}""")
    ]


# --------------------------- 短纲（3 章一段）走向 ---------------------------

SHORT_OPTION_RULES = """你是小说策划，负责为一段（3 章）剧情提供 3 个互斥的发展走向，供作者选择。
要求：
1. 三条走向都必须从【本段开头状态】出发，最终汇聚到【本段最终结果】，不得偏离最终结果；
2. 彼此必须在“怎么走、遇到谁、代价是什么”上明显不同，不能只是措辞差异；
3. 每条必须写清本段反派（人、势力或困境）、主角如何应对、以什么代价在第 3 章解决或退场；
4. 每条给出：标题（6-10 字）、一句话概要（不超过 50 字）、三章推进要点（每章一句）；
5. 只输出 JSON 数组，不要解释、不要代码块标记，格式：
[{"title": "...", "summary": "...", "chapters": ["第1章...", "第2章...", "第3章..."]}]"""


def _short_row(short_id):
    return _fetch_one(
        "SELECT so.*, v.volume_no, v.title AS volume_title, v.outline_id "
        "FROM short_outline so JOIN volume v ON so.volume_id = v.id WHERE so.id = %s",
        (short_id,),
    )


def _parse_short_options(text):
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    try:
        data = json.loads(raw)
    except Exception:
        raise ValueError("短纲走向解析失败，请重试")
    if not isinstance(data, list):
        raise ValueError("短纲走向格式不正确，请重试")
    options = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        chapters = item.get("chapters") or item.get("advance") or []
        if not isinstance(chapters, list):
            chapters = [str(chapters)]
        chapters = [str(c).strip() for c in chapters if str(c).strip()][:3]
        if title and summary:
            options.append({
                "title": title[:30], "summary": summary[:120], "chapters": chapters,
            })
    if len(options) < 3:
        raise ValueError("短纲走向生成不足 3 条，请重试")
    return options[:3]


@monitor.track_step("短纲走向生成")
def generate_short_options(short_id, force=False, note=""):
    """依据短纲的开头状态与最终结果，生成 3 条互斥的发展走向；note 为用户补充想法"""
    short = _short_row(short_id)
    if not short:
        raise ValueError(f"short_outline 表中不存在 id={short_id} 的短纲")
    note = (note or "").strip()
    if not force and not note and (short.get("plot_options") or "").strip():
        try:
            cached = json.loads(short["plot_options"])
            if isinstance(cached, list) and len(cached) >= 3:
                return cached[:3]
        except Exception:
            pass

    count = int(short.get("chapter_count") or 3)
    start_no = _fetch_one(
        "SELECT MIN(chapter_no) AS start_no FROM chapter_outline WHERE short_id = %s",
        (short_id,),
    )
    start_no = (start_no or {}).get("start_no") or 3 * (int(short.get("seq") or 1) - 1) + 1
    antagonist, cast = parse_short_cast(short.get("characters"))
    note_block = ""
    if note:
        note_block = (
            "\n【作者补充想法】\n"
            f"{note}\n"
            "三条走向都必须参考作者的想法来设计；若作者想法与开头/最终结果冲突，"
            "以作者想法为准调整过程，但结尾仍要落到【本段最终结果】。\n"
        )
    prompt = f"""【分卷】第{short['volume_no']}卷《{short['volume_title']}》
【本段短纲】《{short.get('title')}》
- 覆盖章节：第 {start_no}-{start_no + count - 1} 章（共 {count} 章）
- 本段开头状态：{short.get('start_state') or short.get('storyline')}
- 本段最终结果：{short.get('end_state') or short.get('result')}
- 本段反派：{antagonist or '（未指定）'}
- 本段人物：{cast or '（未指定）'}
- 故事线：{short.get('storyline')}
- 主要地点：{short.get('location')}
{note_block}
请给出 3 个互斥的本段发展走向，每条都要写清本段反派与解决方式，最终都要落到【本段最终结果】。"""

    ai = llm.invoke([
        SystemMessage(content=SHORT_OPTION_RULES),
        HumanMessage(content=prompt),
    ])
    options = _parse_short_options(ai.content or "")

    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE short_outline SET plot_options = %s WHERE id = %s",
            (json.dumps(options, ensure_ascii=False), short_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return options


def set_short_choice(short_id, choice_no=None, note=""):
    """记录本段走向：choice_no 为 1-3 选择具体走向，
    note 为用户自己写的走向想法，为空表示交给模型自行处理"""
    short = _short_row(short_id)
    if not short:
        raise ValueError(f"short_outline 表中不存在 id={short_id} 的短纲")
    note = (note or "").strip()

    mode, choice, option = "auto", "", None
    if choice_no in (1, 2, 3):
        options = generate_short_options(short_id)
        option = options[choice_no - 1]
        lines = [f"走向：{option['title']}", f"概要：{option['summary']}"]
        chapters = option.get("chapters") or []
        if chapters:
            lines.append("三章推进：")
            for idx, item in enumerate(chapters[:3], start=1):
                lines.append(f"第{idx}章 {item}")
        if note:
            lines.append(f"作者补充要求：{note}")
        choice = "\n".join(lines)
        mode = "manual"
    elif note:
        choice = f"作者指定走向：{note}"
        mode = "manual"

    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE short_outline SET plot_choice_mode = %s, plot_choice_no = %s, "
            "plot_choice = %s WHERE id = %s",
            (mode, choice_no if mode == "manual" else None, choice or None, short_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return {"short_id": short_id, "mode": mode, "choice": choice, "option": option}


def segment_payload(chapter):
    """把短纲段落信息整理给前端（旧模式返回 None）"""
    if not int(chapter.get("segment_mode") or 0):
        return None
    seg_index, seg_count = _segment_info(chapter)
    options = []
    raw = (chapter.get("plot_options") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                options = parsed
        except Exception:
            options = []
    return {
        "short_id": chapter.get("short_id"),
        "short_title": chapter.get("short_title"),
        "start_state": chapter.get("short_start_state") or "",
        "end_state": chapter.get("short_end_state") or "",
        "storyline": chapter.get("short_storyline") or "",
        "location": chapter.get("short_location") or "",
        "start_no": chapter.get("short_start_no"),
        "seg_index": seg_index,
        "chapter_count": seg_count,
        "mode": chapter.get("plot_choice_mode") or "",
        "choice": chapter.get("plot_choice") or "",
        "options": options,
    }


TITLE_LINE_RE = re.compile(r"^\s*[*#>\s]*标题\s*[:：]\s*(.+?)\s*\**\s*$")


def _parse_title_line(line):
    match = TITLE_LINE_RE.match(line or "")
    if not match:
        return ""
    value = match.group(1).strip()
    return value.strip("《》\"'“”‘’*# ").strip()[:40]


def _split_title(content):
    """拆出正文首行的「标题：xxx」，返回 (标题, 去掉标题行的正文)"""
    text = (content or "").strip()
    if not text:
        return "", ""
    first, sep, rest = text.partition("\n")
    title = _parse_title_line(first)
    if title:
        return title, rest.strip()
    return "", text


def _save_chapter_title(chapter_outline_id, title):
    if not title:
        return
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE chapter_outline SET title = %s WHERE id = %s",
            (title, chapter_outline_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def _save_novel_chapter(chapter, content, status="已完成", title=None):
    title = (title or chapter.get("title") or "").strip() or f"第{chapter['chapter_no']}章"

    conn = _connect()
    cur = conn.cursor()
    insert_sql = """
    INSERT INTO novel_chapter
        (chapter_outline_id, chapter_no, title, content, word_count, status)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        id         = LAST_INSERT_ID(id),
        chapter_no = VALUES(chapter_no),
        title      = VALUES(title),
        content    = VALUES(content),
        word_count = VALUES(word_count),
        status     = VALUES(status);
    """
    try:
        cur.execute(insert_sql, (
            chapter["id"], chapter.get("chapter_no"), title, content,
            _word_count(content), status,
        ))
        conn.commit()
        return cur.lastrowid
    finally:
        cur.close()
        conn.close()


def update_chapter_content(novel_chapter_id, content):
    """去 AI 味润色后覆盖正文，返回新的有效字数"""
    word_count = _word_count(content)
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE novel_chapter SET content = %s, word_count = %s, "
            "status = '已完成', updated_at = NOW() WHERE id = %s",
            (content, word_count, novel_chapter_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return word_count


@monitor.track_step("正文生成")
def novelWriter(state: WriterState):
    """小说写手：依据章纲、世界观、人物、人物关系、伏笔与前文摘要撰写正文"""
    chapter = _select_chapter(state)
    summaries = _previous_summaries(
        chapter["volume_no"], chapter["short_seq"], chapter["chapter_no"],
        chapter.get("outline_id"),
    )
    ending = _previous_ending(
        chapter["volume_no"], chapter["short_seq"], chapter["chapter_no"],
        chapter.get("outline_id"),
    )
    target_words = min(3000, max(2000, chapter.get("target_words") or 2500))
    audit_issues = (state.get("audit_issues") or "").strip()

    ai = llm.invoke(_writer_messages(
        chapter, summaries, ending, audit_issues, target_words,
        scene_choice=(state.get("scene_choice") or "").strip(),
    ))
    content = ai.content or ""
    title = ""
    if not _is_legacy(chapter):
        title, content = _split_title(content)
        if title:
            _save_chapter_title(chapter["id"], title)
    content = content.strip()

    novel_chapter_id = _save_novel_chapter(chapter, content, title=title or None)
    return {
        "novel_chapter_id": novel_chapter_id,
        "chapter_outline_id": chapter["id"],
        "content": content,
    }


@monitor.track_step("正文流式生成")
async def novelWriterStream(state: WriterState):
    """流式写手：逐块产出 {"type": "delta", "text": ...}，结束后落库并产出 done 事件"""
    chapter = _select_chapter(state)
    draft_text = ""
    if state.get("resume"):
        draft_text = (chapter.get("draft_content") or "").strip()
    summaries = _previous_summaries(
        chapter["volume_no"], chapter["short_seq"], chapter["chapter_no"],
        chapter.get("outline_id"),
    )
    ending = _previous_ending(
        chapter["volume_no"], chapter["short_seq"], chapter["chapter_no"],
        chapter.get("outline_id"),
    )
    target_words = min(3000, max(2000, chapter.get("target_words") or 2500))
    audit_issues = (state.get("audit_issues") or "").strip()

    messages = _writer_messages(
        chapter, summaries, ending, audit_issues, target_words, draft_text,
        scene_choice=(state.get("scene_choice") or "").strip(),
    )

    parts = []
    completed = False
    # 短纲模式：正文首行由写手给出「标题：xxx」，先缓冲首行再回写标题
    expect_title = (not _is_legacy(chapter)) and not state.get("resume")
    head_done = not expect_title
    head_buf = ""
    title = ""

    # 断点保护：生成过程中定期把已写内容存成草稿，
    # 即使进程被杀、断网或余额耗尽，也能从最近一次快照续写
    snapshot_ok = _can_snapshot(chapter["id"])
    written = 0
    saved_chars = 0
    saved_at = time.monotonic()

    def _maybe_snapshot():
        nonlocal saved_chars, saved_at
        if not snapshot_ok or not parts:
            return
        now = time.monotonic()
        if written - saved_chars < 400 and now - saved_at < 5:
            return
        try:
            _save_novel_chapter(
                chapter, (draft_text + "".join(parts)).strip(),
                "草稿", title or None,
            )
            saved_chars = written
            saved_at = now
        except Exception:
            pass

    try:
        async for chunk in llm.astream(messages):
            text = chunk.content or ""
            if not text:
                continue
            if not head_done:
                head_buf += text
                if "\n" in head_buf:
                    head_line, _, rest = head_buf.partition("\n")
                    title = _parse_title_line(head_line)
                    if title:
                        _save_chapter_title(chapter["id"], title)
                        out = rest
                    else:
                        out = head_line + "\n" + rest
                    head_done = True
                    head_buf = ""
                    if out:
                        parts.append(out)
                        written += len(out)
                        yield {"type": "delta", "text": out}
                        _maybe_snapshot()
                    continue
                if len(head_buf) < 200:
                    continue
                # 首行过长仍未换行，放弃标题解析，按正文输出
                head_done = True
                out, head_buf = head_buf, ""
                parts.append(out)
                written += len(out)
                yield {"type": "delta", "text": out}
                _maybe_snapshot()
                continue
            parts.append(text)
            written += len(text)
            yield {"type": "delta", "text": text}
            _maybe_snapshot()

        if not head_done and head_buf:
            head_line, _, rest = head_buf.partition("\n")
            title = _parse_title_line(head_line)
            if title:
                _save_chapter_title(chapter["id"], title)
                tail = rest
            else:
                title = ""
                tail = head_buf
            head_done = True
            head_buf = ""
            if tail:
                parts.append(tail)
                written += len(tail)
                yield {"type": "delta", "text": tail}
                _maybe_snapshot()

        content = (draft_text + "".join(parts)).strip()
        novel_chapter_id = _save_novel_chapter(
            chapter, content, "已完成", title or None
        )
        completed = True
        yield {
            "type": "done",
            "novel_chapter_id": novel_chapter_id,
            "chapter_outline_id": chapter["id"],
            "chapter_no": chapter.get("chapter_no"),
            "title": title or chapter.get("title"),
            "word_count": _word_count(content),
        }
    finally:
        # 客户端断开或生成中断时，把已生成内容保存为草稿，供下次续写
        if not completed:
            try:
                tail = ""
                if head_buf and not head_done:
                    # 首行缓冲还没解析出标题，先把标题行剔除，剩余部分算正文
                    head_line, _, rest = head_buf.partition("\n")
                    parsed = _parse_title_line(head_line)
                    if parsed:
                        title = title or parsed
                        tail = rest
                    else:
                        tail = head_buf
                partial = (draft_text + "".join(parts) + tail).strip()
                existing = _fetch_one(
                    "SELECT status FROM novel_chapter WHERE chapter_outline_id = %s",
                    (chapter["id"],),
                )
                # 已有完整正文时不覆盖，避免重写中断丢掉原稿
                if partial and (not existing or existing.get("status") == "草稿"):
                    _save_novel_chapter(chapter, partial, "草稿", title or None)
            except Exception:
                pass


# ------------------------------- 摘要总结 -------------------------------

def _apply_story_state(row, ai):
    """把本章人物状态与伏笔推进回写到数据库，供后续章节使用"""
    chapter_no = row.get("chapter_no")
    state_map = {"埋设": "已埋", "推进": "推进中", "回收": "已回收"}
    outline_row = _fetch_one(
        """
        SELECT v.outline_id FROM novel_chapter nc
        JOIN chapter_outline co ON nc.chapter_outline_id = co.id
        JOIN short_outline so ON co.short_id = so.id
        JOIN volume v ON so.volume_id = v.id
        WHERE nc.id = %s
        """,
        (row.get("id"),),
    )
    outline_id = (outline_row or {}).get("outline_id")

    conn = _connect()
    cur = conn.cursor()
    try:
        for item in getattr(ai, "person_states", []) or []:
            name = (item.name or "").strip()
            if not name:
                continue
            if outline_id:
                cur.execute(
                    "UPDATE person SET current_state = %s, current_location = %s, "
                    "last_chapter_no = %s WHERE outline_id = %s AND name = %s",
                    (item.state or "", item.location or "", chapter_no,
                     outline_id, name),
                )
            else:
                cur.execute(
                    "UPDATE person SET current_state = %s, current_location = %s, "
                    "last_chapter_no = %s WHERE name = %s",
                    (item.state or "", item.location or "", chapter_no, name),
                )
        for item in getattr(ai, "foreshadow_updates", []) or []:
            name = (item.name or "").strip()
            if not name:
                continue
            status = state_map.get((item.action or "").strip())
            if not status:
                continue
            if outline_id:
                cur.execute(
                    "UPDATE foreshadow SET status = %s, last_chapter_no = %s "
                    "WHERE outline_id = %s AND name = %s",
                    (status, chapter_no, outline_id, name),
                )
            else:
                cur.execute(
                    "UPDATE foreshadow SET status = %s, last_chapter_no = %s "
                    "WHERE name = %s",
                    (status, chapter_no, name),
                )
        conn.commit()
    finally:
        cur.close()
        conn.close()


@monitor.track_step("章节摘要")
def chapterSummarizer(state: WriterState):
    """摘要总结：对已写正文做结构化摘要，供后续章节续写使用"""
    novel_chapter_id = state.get("novel_chapter_id")
    if novel_chapter_id:
        row = _fetch_one(
            "SELECT * FROM novel_chapter WHERE id = %s", (novel_chapter_id,)
        )
    else:
        row = _fetch_one(
            "SELECT * FROM novel_chapter "
            "WHERE content IS NOT NULL AND content <> '' "
            "AND (summary IS NULL OR summary = '') "
            "ORDER BY id DESC LIMIT 1"
        )
        if not row:
            row = _fetch_one("SELECT * FROM novel_chapter ORDER BY id DESC LIMIT 1")
    if not row or not row.get("content"):
        raise ValueError("novel_chapter 表中没有可摘要的正文，请先执行 novelWriter")

    structured_llm = summary_llm.with_structured_output(ChapterSummary)
    ai = structured_llm.invoke([
        SystemMessage(
            "你是剧情梗概记录员，只写主线事实，不写细节。"
            "禁止形容词、比喻、拟人、夸张，禁止环境、天气、光线、声音、气味、外貌、"
            "他人情绪和主观评价；省略过程性动作（怎么走、怎么搬、怎么打），"
            "只保留推动剧情的关键行动、遭遇和结果。"
        ),
        HumanMessage(content=f"""【章节】
第{row.get('chapter_no')}章《{row.get('title')}》

【正文】
{row['content']}

要求：
1. summary 是剧情梗概，不是细节复述：100-150 字，最多 4 句，只写主角的关键行动、遭遇和结果；
2. 省略过程：不写怎么走路、怎么搬书、怎么扫地、招式动作、对话细节、他人外貌和反应；
3. 反例：“瘦高个踢他小腿使他单膝磕地，又揪后领将他搡在地上”“石面浮起灰暗稀薄的光”；
   正例：“林恩被判为劣等灵根，罚去禁书库做杂役”“他获得吞噬法术残渣的能力”“格里芬上门巡查，他藏起黑书应对”；
4. summary 不写心理活动、不写情绪、不写作者评论，只写可观察到的事实；
5. 人名、地点、物品、数字必须与原文一致，不虚构、不省略关键结果；
6. key_points 列出 3-6 个关键情节点，用分号分隔，同样只写事实；
7. characters 写明出场人物及其本章中的状态变化（受伤、知情、立场变化等）；
8. foreshadow 写明本章埋下或推进了哪些伏笔，没有则填“无”；
9. next_hook 写明章尾发生了什么、下一章需要从哪里接续，只写事实；
10. person_states 只列本章结束时状态发生变化的人物：name 必须与人物档案完全一致，
    state 写事实（受伤、境界变化、获得物品、知情、立场变化），location 写当前所在地点；
11. foreshadow_updates 只列本章实际处置的伏笔：name 必须与伏笔清单完全一致，
    action 只能填“埋设”“推进”“回收”，没有则返回空列表。""")
    ])

    _apply_story_state(row, ai)

    conn = _connect()
    cur = conn.cursor()
    update_sql = """
    UPDATE novel_chapter
    SET summary = %s,
        summary_points = %s,
        summary_characters = %s,
        summary_foreshadow = %s,
        summary_time = NOW()
    WHERE id = %s
    """
    try:
        cur.execute(update_sql, (
            ai.summary, ai.key_points, ai.characters, ai.foreshadow, row["id"],
        ))
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return {
        "novel_chapter_id": row["id"],
        "content": row["content"],
        "summary": ai.summary,
    }
