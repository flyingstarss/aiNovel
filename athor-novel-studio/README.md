# Athor Novel Studio

一个基于 DeepSeek 的 AI 长篇小说创作工作台。从一句需求出发，自动完成世界观、大纲、分卷、地图、伏笔、短纲、章纲与正文，并在写作过程中执行字数、违规、一致性、文风与 AI 味审核。

前端为原生 HTML/JS，后端为 FastAPI + MySQL，全部生成过程通过 SSE 流式返回，可实时看到模型输出。

---

## 功能

| 模块 | 能力 |
| --- | --- |
| 多会话 | 会话之间数据完全隔离，侧边栏切换，刷新后回到最近一本书 |
| 世界观 | 每本书首次生成大纲时创建专属世界观，不与旧书串用 |
| 大纲 | 流式生成、在线修改、人工审核、版本留档；支持上传 TXT 自动识别编码并生成大纲 |
| 结构 | 分卷、地图、伏笔、逐卷短纲与章节占位，按卷推进，不一次性生成全书 |
| 短纲 | 每 3 章为一个故事单元，给出 3 个互斥剧情方向，支持自定义想法 |
| 正文 | 逐章流式写作，单章 2000–3000 字，自动拆分标题、生成摘要、回写人物状态与伏笔 |
| 审核 | 字数、违规词库、加权一致性（细纲 40% / 人物 30% / 伏笔 20% / 连贯 10%）、比喻与文风硬拦截 |
| 改写 | 命中问题优先局部重写，无法定位才整章重写，最多 3 轮 |
| AI 味 | 分项扣分制评分，只润色命中段落，候选稿与当前最优稿比分数，低分回退 |
| 断流保护 | 每 400 字或 5 秒持久化草稿，中断后可「续写本章」，不覆盖已生成内容 |
| 阅读 | 独立阅读页、设定集、书目列表、TXT 导出 |
| 观测 | 每步 token 消耗与耗时统计，前端可查 |

---

## 技术栈

- Python 3.11+
- FastAPI 0.136 + Uvicorn
- MySQL 8 + PyMySQL（内置连接池）
- LangChain Core + langchain-deepseek（DeepSeek Chat）
- 原生 HTML / CSS / JavaScript（无构建步骤）

---

## 快速开始

### 1. 准备

- Python 3.11 或更高版本
- MySQL 8，已创建可用的账号（需要建库权限）
- DeepSeek API Key

### 2. 安装

```bash
git clone <your-repo-url>
cd athor-novel-studio

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. 配置

```bash
# Windows
copy .env.example .env
# macOS / Linux
cp .env.example .env
```

编辑 `.env`，至少填写：

```ini
DEEPSEEK_API_KEY=你的密钥
DB_USER=root
DB_PASSWORD=你的数据库密码
```

其余参数保持默认即可。

### 4. 初始化数据库

新库：

```bash
python scripts/init_db.py
```

已有旧库（v5 及以前）再执行一次增量迁移：

```bash
python scripts/migrate_v6.py
```

### 5. 启动

```bash
python run.py
```

- 工作台：http://127.0.0.1:8000
- 阅读页：http://127.0.0.1:8000/reader

---

## 使用流程

1. 新建会话，输入一句小说需求（例如“废土世界，主角靠修复旧时代机器崛起”）
2. 生成大纲 → 在线修改 → 审核通过
3. 生成结构：分卷、地图、伏笔，以及第 1 卷短纲和章节占位
4. 每卷开始前选择剧情方向，然后逐章写作
5. 每章自动完成：正文 → 摘要 → 审核 → 局部重写 / 润色 → 保存最高分版本
6. 在阅读页查看成书、设定集，或导出 TXT

---

## 架构

```
展示层  web/index.html · web/reader.html
   │  HTTP / SSE
接口层  app/routers/*（参数校验、流式返回、进度汇总）
   │
应用层  editor（设定/大纲/结构） writer（正文/摘要/草稿）
        reviewer（违规/一致性）  humanizer（AI 味评分/润色）
        session_store（会话隔离）
   │
能力层  llm（模型工厂/温度分层） monitor（token/耗时） sse（心跳/并发）
   │
数据层  MySQL（业务实体） · data/（草稿） · logs/（用量日志）
```

编排采用前端驱动的分步流式链路：大纲、结构、写作各自独立接口，每步落库，可中断、可重入。

### 目录

```
athor-novel-studio/
├── app/
│   ├── main.py            # FastAPI 入口与页面分发
│   ├── config.py          # 环境变量配置
│   ├── db.py              # MySQL 连接池与查询封装
│   ├── llm.py             # 按角色创建模型实例
│   ├── monitor.py         # token / 耗时监控
│   ├── sse.py             # SSE 心跳与并发控制
│   ├── schemas.py         # 请求模型
│   ├── agents/
│   │   ├── editor.py      # 世界观、人物、大纲、分卷、短纲、地图、伏笔
│   │   ├── writer.py      # 上下文裁剪、正文生成、摘要、草稿
│   │   ├── reviewer.py    # 违规审核、一致性审核
│   │   ├── humanizer.py   # AI 味评分与润色
│   │   └── session_store.py
│   └── routers/           # sessions / outline / structure / chapters / library / usage
├── web/
│   ├── index.html         # 创作工作台
│   └── reader.html        # 阅读页
├── scripts/
│   ├── schema.sql         # 建表语句
│   ├── init_db.py         # 幂等初始化
│   ├── migrate_v2..v6.py  # 增量迁移
│   └── reset_outline.py   # 按书重置结构（危险操作，谨慎使用）
├── data/                  # 运行期草稿（不入库）
├── logs/                  # 运行期日志（不入库）
├── requirements.txt
├── .env.example
└── run.py
```

---

## 配置说明

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 模型密钥，必填 | 空 |
| `DEEPSEEK_MODEL` | 模型名 | `deepseek-v4-flash` |
| `DEEPSEEK_BASE_URL` | 接口地址 | 空（使用 SDK 默认） |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` | MySQL 连接 | `127.0.0.1:3306`，`root` |
| `DB_NAME` | 业务库名 | `novel_world` |
| `DB_POOL_SIZE` | 连接池上限 | `5` |
| `LLM_MAX_TOKENS` | 单次输出上限 | `8192` |
| `LLM_STREAM_CHUNK_TIMEOUT` | 流式 chunk 等待上限，0 不限制 | `0` |
| `LLM_MAX_RETRIES` | 接口失败重试次数 | `3` |
| `LLM_CONCURRENCY` | 同时生成任务上限 | `3` |
| `LLM_TEMP_*` | 各角色的温度 | 总编/写手 0.8，审核/摘要 0.2，润色 0.35 |

---

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/sessions` | 新建会话 |
| GET | `/api/sessions` | 会话列表 |
| PATCH | `/api/sessions/{id}` | 更新会话状态 |
| GET | `/api/sessions/{id}/messages` | 会话消息 |
| POST | `/api/outline/stream` | 流式生成大纲 |
| POST | `/api/outline/revise/stream` | 按意见流式修改大纲 |
| POST | `/api/outline/import` | 上传 TXT 生成大纲 |
| GET | `/api/outline/{id}` | 读取大纲 |
| PUT | `/api/outline/{id}` | 在线编辑大纲 |
| POST | `/api/outline/review` | 提交人工审核 |
| POST | `/api/structure/stream` | 生成结构（分卷/地图/伏笔/首卷） |
| POST | `/api/volume/stream` | 逐卷生成短纲与章节占位 |
| GET | `/api/progress` | 全书进度 |
| GET | `/api/chapter/next` | 下一章待写信息 |
| POST | `/api/short/options` | 生成 3 个剧情方向 |
| POST | `/api/short/choice` | 保存选定方向 |
| POST | `/api/chapter/stream` | 流式写作一章 |
| POST | `/api/chapter/summarize` | 补生成摘要 |
| POST | `/api/chapter/audit` | 审核单章 |
| POST | `/api/chapter/polish` | 润色单章 |
| GET | `/api/library/books` | 书目 |
| GET | `/api/library/chapters` | 章节列表 |
| GET | `/api/library/latest` | 最新章节 |
| GET | `/api/library/chapters/{id}` | 章节详情 |
| GET | `/api/library/settings` | 设定集（世界观/人物/关系/地点/伏笔） |
| GET | `/api/library/download` | 导出 TXT |
| GET | `/api/usage` | token 与耗时统计 |

---

## 数据隔离

设定层与结构层均按 `outline_id` 归属到具体一本书：

- `worldview`、`person`、`person_relation`、`story_map`、`foreshadow` 都带 `outline_id`
- 唯一键按 `(outline_id, name)` 组合，不同书可以出现同名人物、地点、伏笔
- 世界观在大纲生成后回填 `outline_id`
- 人物状态与伏笔推进回写时限定当前书，不会误改其他书

---

## 已知限制

- 单机单用户设计，**没有登录与权限**，请勿直接暴露到公网
- 生成质量依赖所配置的模型，API 费用由使用者自行承担
- 所有生成内容需自行做合规与版权审查
- 前端为单文件内联页面，未做组件化与构建优化
- 旧库升级需手动执行迁移脚本，无自动化迁移框架

---

## 安全提示

- `.env` 已被 `.gitignore` 排除，请勿提交真实密钥与数据库密码
- 公开部署前请补充鉴权、限流、CORS 与上传大小限制
- `scripts/reset_outline.py` 会删除指定书的结构与章节，使用前务必备份数据库

---

## 设计参考

AI 味处理思路参考了 Humanizer-zh 的去 AI 味方法，并按本项目需求做了定制实现，未直接包含其源码。
