# Quant Marketing Daily — 项目规格书

> 版本: 3.1 | 日期: 2026-07-02 | 状态: 已与实现对齐（唯一验收标准）

---

## 1. 项目概述

每天自动抓取 Quantitative Marketing 领域五大顶刊的最新论文，经 LLM 翻译+摘要后生成结构化中文日报。
通过多种渠道（GitHub Pages / 即时通讯 / 邮件）触达用户。

### 1.1 目标用户

Quantitative Marketing 研究者，需要每天了解领域内的最新发表。

### 1.2 覆盖期刊

| 期刊缩写 | 全称 | 出版商 | ISSN |
|---|---|---|---|
| JM | Journal of Marketing | Sage / AMA | 0022-2429 |
| JMR | Journal of Marketing Research | Sage / AMA | 0022-2437 |
| MktSci | Marketing Science | INFORMS | 0732-2399 |
| QME | Quantitative Marketing and Economics | Springer | 1570-7156 |
| MngSci | Management Science (Marketing dept.) | INFORMS | 0025-1909 |

### 1.3 Quant relevance profile

本项目不是泛 marketing digest，而是面向 quantitative marketing / empirical IO / platform / pricing / AI-enabled marketing research。候选论文在候选池截断前必须按 quant relevance 优先保留，避免 consumer psychology / behavioral marketing 论文挤掉核心 quant paper。

核心正向信号包括：structural model、demand estimation、discrete choice、causal inference、identification、field experiment、pricing、platform、two-sided market、network effect、LLM、large language model、generative AI、recommendation、recommender system。

低优先级 behavioral/psych 信号包括：emotion、identity、mindset、attitude、persuasion、well-being、stigma、language framing、gesture、aesthetics、subjective poverty。低优先级不是硬删除；若论文同时包含 field experiment、pricing、platform、causal identification 等强 quant 信号，仍可进入核心候选。

期刊优先级只作为同一 relevance 层级内的 tie-breaker，并同时决定日报板块展示顺序：MktSci → QME → MngSci → JMR → JM → SSRN。

### 1.4 日报命名

日报文件名为 `output/YYYY-MM-DD.md`，标题为 `Quant Marketing Daily — YYYY-MM-DD`。`Daily` 而非 `Today`，更准确反映每日汇总语义。

---

## 2. 传递形式

### 2.1 主力：GitHub Actions → Markdown 日报（P0，已完成）

```
GitHub Actions (每日定时 cron: 7 9 * * *, timezone: Asia/Shanghai = 北京时间 09:07)
→ 10 步管线抓取 + 生成 Markdown
→ 产出 output/YYYY-MM-DD.md
→ commit seen_dois.json 回 main
```

> **时区约定**：Actions schedule 显式使用 `timezone: Asia/Shanghai`；日报文件名、日期过滤窗口也均以 **Asia/Shanghai (UTC+8)** 为准。所有日期计算使用 `zoneinfo.ZoneInfo("Asia/Shanghai")`。

#### 状态持久化

```
data/seen_dois.json   ← 已推送论文注册表（每次运行后 commit 更新）
output/YYYY-MM-DD.md  ← 每日日报（按日期命名）
```

`seen_dois.json` 必须持久保留。删掉会导致下次运行对已见论文重复报道。

#### Actions 并发防护

```yaml
concurrency:
  group: daily-run
  cancel-in-progress: false
```

加上 `git pull --rebase` → commit → push。push 被 reject 时重试一次。

### 2.2 即时推送：Coze Bot（P1，待实现）

GitHub Actions 生成日报后 → POST Webhook 到 Coze Bot → 飞书/企业微信。

### 2.3 邮件推送（P1，基础实现）

GitHub Actions 在日报生成后可选调用 `src/notify_email.py`，通过 SMTP 将最新 `output/YYYY-MM-DD.md` 发送给一个或多个收件人。邮件包含纯文本和基础 HTML 两种格式。

必需配置通过 Actions Secrets 注入：`SMTP_SERVER`、`SMTP_USERNAME`、`SMTP_PASSWORD`、`NOTIFY_EMAIL`；`SMTP_PORT` 默认 587，`SMTP_FROM` 默认等于 `SMTP_USERNAME`。

### 2.4 分发原则

- 分发只在管线成功生成日报后触发；`--dry-run` 不触发分发
- 分发失败不应污染 `seen_dois.json`
- 邮件推送是可选通道；未配置 SMTP secrets 时跳过
- GitHub Pages 和 Coze Bot 仍为 P1 待实现通道

---

## 3. Fetch 规则

### 3.1 双日期模型

| 日期 | 用途 | 来源 |
|---|---|---|
| **`online_date`** | 决定是否进入日报（过滤用） | RSS `updated` / `published_parsed` |
| **`coverdate`** | 日报中的展示标签 | RSS `prism_coverdate` |

**提取优先级**：
```
online_date  ←  1. updated_parsed (Articles in Advance 首发日)
                 2. published_parsed (Springer 论文级日期)
                 3. prism_coverdate (兜底：无在线日期时用封面日期)
                 4. "" (不过滤，保守保留)

coverdate    ←  1. prism_coverdate (封面日期，最准确)
                 2. "" (无封面日期时不展示标签)
```

### 3.2 日期过滤窗口

```
if 今天在当月前 7 天:
    fetch_from = 上月1号
else:
    fetch_from = 今天 - 30天

fetch_to = 今天
```

| 今天 | 条件 | fetch_from | 窗口大小 |
|---|---|---|---|
| 7月1日 | ≤ 7 天 | 6月1日 | ~31 天 |
| 7月7日 | ≤ 7 天 | 6月1日 | ~37 天 |
| 7月8日 | > 7 天 | 6月8日 | 30 天 |
| 7月15日 | > 7 天 | 6月15日 | 30 天 |

`online_date` 为空时不过滤（保守保留）。

---

## 4. 摘要抓取策略

### 4.1 三级回退

```
出版商详情页/Crossref ──► Playwright/Scrapling 原文页 ──► Semantic Scholar API
      (优先)                    (MktSci 补抓)          (兜底)
```

| 出版商 | 一级来源 | 二级兜底 | 说明 |
|--------|---------|---------|------|
| Sage | Crossref JSON | S2 API | `scraper/sage.py` — doi.org 代理 |
| INFORMS | Crossref JSON | Playwright/Scrapling + S2 API | `scraper/informs.py` — 含 MktSci 缓存 |
| Springer | RSS `<link>` HTML | — | `scraper/springer.py` |

### 4.2 INFORMS 原文页补抓

INFORMS 详情页有 **Cloudflare Turnstile** 防护，直接 HTTP 经常返回 403。因此默认策略仍以 Crossref JSON 为稳定元数据来源；当 MktSci 只拿到短摘要时，先尝试 Playwright 持久化 profile，再使用 Scrapling 对原文页做 best-effort 补抓。补抓失败不阻塞日报，仍保留 Crossref/S2 摘要并写入 `data/pending_mktsci.json` 供人工或云端补缓存。

### 4.3 MktSci 特殊处理

```
MktSci 论文
  ├─ data/mktsci_abstracts.json 缓存命中 → 返回完整摘要
  ├─ Crossref（通常 ~150 字符短摘要）
  ├─ Playwright 持久化 profile 补抓成功 → 写入缓存并返回完整摘要
  ├─ Scrapling 原文页补抓成功 → 写入缓存并返回完整摘要
  └─ S2 兜底
```

Playwright 默认使用 `data/.pw-profile/` 作为持久化 profile。若需要人工通过 Turnstile，可本地设置 `INFORMS_PW_HEADLESS=0` 运行一次；后续 cookie 复用。Scrapling 静态 fetch 默认启用；浏览器 stealth 模式通过 `.env` 中 `INFORMS_USE_STEALTH=1` 显式开启，避免定时任务卡在 Cloudflare。`enrich_mktsci.py` 仍保留，用于处理 `pending_mktsci.json` 中自动补抓失败的 DOI。

### 4.4 性能约束

- 摘要抓取仅在 seen + date 预过滤 + 截断后执行（不对已见/过期论文浪费请求）
- 每日最大候选数由 `MAX_CANDIDATE_PAPERS` 控制，当前为 50 篇，使用 relevance-first 截断
- 每篇文章请求间隔 ≥ 2 秒（礼貌限速）
- S2 API 有共享限速客户端（`_semantic_scholar.py`）
- 单篇抓取失败不阻塞管线，标记 `abstract_missing=True`

---

## 5. MngSci 过滤（两阶段）

仅 Management Science 需要过滤——该刊覆盖所有管理学科。

### 阶段一：Quant relevance 截断与 MngSci tie-breaker（步骤 [4]）

标题关键词预判，零 HTTP 调用，仅影响截断排序。全体期刊先计算 quant relevance，Management Science 额外使用标题级 marketing boost：

```
全体论文  → quant relevance tier（core_quant / quant_relevant / broad_marketing / low_priority）
MngSci 论文 + 标题含 marketing 关键词 → boost=0（同层内排前）
                                否则 → boost=1
```

目的：防止核心 quant paper 被新近但低相关的 behavioral/psych paper 挤出候选上限。

### 阶段二：正式过滤（步骤 [6]）

摘要抓取完成后，`mngsci_accepted_by` 字段已有数据：

```
优先：_is_marketing_by_accepted()
  ├─ accepted_by 含 "marketing" → 保留
  ├─ accepted_by 含非 marketing 部门 → 丢弃
  └─ accepted_by 为空或 VSI → 进兜底

兜底：_keyword_score(title + abstract)
  ├─ pos - neg ≥ 2 → 保留
  └─ otherwise → 丢弃
```

- **不再区分** confirmed / [uncertain] 两级
- Cross `accepted_by` 信号可靠性远高于关键词比分
- 关键词比分的 `pos - neg ≥ 2` 阈值经 54 篇实际论文数据验证

---

## 6. LLM 集成

### 6.1 架构

```
标题翻译 (step [7])          AI 摘要 (step [8])
     ↓                             ↓
  translate.py                 abstract.py
     ↓                             ↓
         ┌──── llm.py (统一客户端) ────┐
         ↓                             ↓
    DeepSeek API                  Ollama (qwen2.5:7b)
     (优先)                         (回落)
         ↓                             ↓
              └── 降级（留空，不崩溃）──┘
```

### 6.2 配置

通过 `.env` 文件（`python-dotenv` 自动加载）：

```bash
# quant-marketing-daily/.env
DEEPSEEK_API_KEY=sk-xxx          # 优先
DEEPSEEK_BASE_URL=https://api.deepseek.com
OLLAMA_BASE_URL=http://localhost:11434  # 回落
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_TIMEOUT=300
```

本地开发用 `.env`，GitHub Actions 用 Secrets。

### 6.3 双层输出

| 字段 | Prompt | 用途 |
|------|--------|------|
| `title_zh` | 学术翻译，含中英对应 | 日报中紧跟英文标题展示 |
| `one_line_summary` | 一句话（40-60 字） | 列表视图快速浏览 |
| `abstract_zh` | 完整翻译，逐句对应 | `<details>` 折叠区，不遗漏任何信息 |

LLM 不可用时（无 API Key 且无 Ollama）：字段留空，日报正常生成但仅展示英文摘要。

---

## 7. 输出格式

### 7.1 日报结构

```markdown
# Quant Marketing Daily — 2026-07-02

_2026-06-01 ~ 2026-07-02 · 20 篇新论文 · 4 个来源_

## 目录
- [Journal of Marketing (X 篇)](#journal-of-marketing-x-篇)
- ...

---
## Journal of Marketing (X 篇)

- **English Paper Title**
  *中文译名*
  *Smith, Jones, Wang et al.*
  `2026-07` · `Vol.90(4)` · `doi:10.1177/...`
  **AI 总结：** 一句话中文摘要（40-60 字）
  **原文链接：** [Source](https://doi.org/...)

  <details>
  <summary><b>展开详情</b></summary>

  **Abstract:** Full English abstract...
  **中文翻译：** 完整中文翻译...
  </details>
```

### 7.2 格式规范（8 行 + 折叠）

| 行 | 内容 | 格式 | 来源 |
|----|------|------|------|
| 1 | 英文标题 | `**粗体**` | RSS `<title>` |
| 2 | 中文译名 | `*斜体*` | LLM `title_zh` |
| 3 | 作者 | `*斜体*`，≥4 位时前 3 + `et al.` | RSS |
| 4 | 元数据 | `` `YYYY-MM` · `Vol.XX(I)` · `doi:10.xxx/...` `` | RSS + DOI |
| 5 | AI 总结 | `**AI 总结：**` | LLM |
| 6 | 原文链接 | `**原文链接：** [Source](url)` | DOI/RSS |
| 7 | 展开详情 | `<details>` 内含英文摘要 + 中文翻译 | scraper + LLM |
| 8 | 折叠闭合 | `</details>` | — |

### 7.3 摘要缺失

当 `abstract_missing=True` 时，即使无摘要也渲染 `<details>` 折叠区，在其中标记 `[摘要缺失]`。

### 7.4 SSRN

通过 `--include-ssrn` flag 控制的 P2 补充来源，在日报末尾增加 `## SSRN — 最新 Working Papers` 板块。

---

## 8. 管线架构

### 8.1 10 步管线

```
[1] RSS 发现         → papers[]（元数据，无摘要）
[2] DOI 标准化 + 去重  → 同次运行内去重
[3] seen + date 预过滤 → 排除已见 + 过期
[4] 候选池截断        → 有日期 → quant relevance → 期刊优先级 → 日期↓ → MngSci 营销 tie-breaker → 标题
[5] 摘要抓取          → 三级回退补全 abstract
[6] MngSci 过滤       → accepted_by 主导 + 关键词兜底（先过滤，减少 LLM 成本）
[7] 标题翻译          → LLM batch → title_zh
[8] AI 双层摘要       → LLM per-paper → one_line_summary + abstract_zh
[9] 渲染 + 保存       → output/YYYY-MM-DD.md
[10] commit seen_dois  → 成功后写注册表
```

### 8.2 模式

```bash
python -m src.fetch              # 正常 — 完整 10 步
python -m src.fetch --dry-run    # 仅 1-4 步，不抓摘要、不写 seen
python -m src.fetch --rebuild    # 忽略 seen 重建当日窗口日报，不写 seen
python -m src.fetch --include-ssrn  # P0 + SSRN
```

### 8.3 关键设计

- MngSci 过滤在标题翻译**之前**（步骤 6），避免浪费 LLM 资源在非营销论文
- 摘要抓取在截断**之后**（步骤 5），不对已截断论文浪费 HTTP 请求
- 截断前先按 quant relevance 保留核心论文，期刊优先级只作为同层级 tie-breaker
- seen_dois 在管线**成功后才 commit**（步骤 10），失败不污染注册表
- 正常模式若同一天已有论文数更多的日报，应保留已有文件，只更新 seen 状态，避免增量小报告覆盖完整 rebuild 报告
- `--rebuild` 用于重建被覆盖/损坏的当日窗口日报，忽略 seen 但不写 seen

### 8.4 Paper Dict 数据模型

管线内部以 `dict` 表示论文。新增来源或新增 scraper 时，至少要保证核心字段存在，并尽量补齐展示和过滤字段。

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `id` | str | RSS/parser | `doi:10.xxx/...` 或无 DOI 时的稳定 hash |
| `title` | str | RSS/parser | 清洗后的英文标题 |
| `authors` | list[str] | RSS/parser | 作者列表；渲染时超过 3 位显示 `et al.` |
| `abstract` | str\|None | scraper/cache/API | 英文摘要，来自 Crossref、出版商页、Scrapling、S2 或缓存 |
| `abstract_missing` | bool | scraper | 摘要缺失标记；缺失时仍渲染 details 并显示 `[摘要缺失]` |
| `journal` | str | config/parser | 期刊 key，例如 `JM`、`JMR`、`MktSci`、`QME`、`MngSci` |
| `journal_full` | str | config | 期刊全名 |
| `publisher` | str | config/parser | `Sage`、`INFORMS`、`Springer`、`SSRN` 等 |
| `doi` | str\|None | RSS/parser | DOI 标识符 |
| `url` | str | RSS/DOI/parser | 原文链接 |
| `online_date` | str | RSS/parser | 过滤用日期，优先 `updated/published` |
| `coverdate` | str | RSS/parser | 展示用日期，优先 `prism_coverdate` |
| `volume` | str\|None | RSS | 卷号 |
| `issue` | str\|None | RSS | 期号 |
| `startpage` | str\|None | RSS | 起始页 |
| `endpage` | str\|None | RSS | 结束页 |
| `needs_filter` | bool | config | 仅 `MngSci=True` |
| `mngsci_accepted_by` | str\|None | Crossref | Management Science 部门信息 |
| `title_zh` | str | LLM | 中文译名 |
| `one_line_summary` | str | LLM | 一句话中文总结 |
| `abstract_zh` | str | LLM | 完整中文摘要翻译 |

---

## 9. 项目结构

```
quant-marketing-daily/
├── .github/workflows/daily.yml   # GitHub Actions 调度
├── docs/
│   └── project_spec.md           # 唯一规格与验收标准
├── src/
│   ├── fetch.py                  # 主入口（10 步管线编排）
│   ├── config.py                 # 全局配置
│   ├── dedup.py                  # DOI 去重 · seen 注册表 · 日期窗口 · relevance-first 截断
│   ├── filter_mngsci.py          # MngSci → Marketing 双策略过滤
│   ├── relevance.py              # Quant relevance 打分与截断排序信号
│   ├── llm.py                    # 统一 LLM 客户端（DeepSeek → Ollama → 降级）
│   ├── translate.py              # LLM 批量标题翻译
│   ├── abstract.py              # LLM 双层摘要（逐篇生成）
│   ├── render.py                 # Markdown 渲染 + 保存
│   ├── enrich_mktsci.py          # MktSci 完整摘要缓存管理 CLI
│   ├── process_pending.py        # MktSci 待补摘要 URL 诊断工具
│   ├── notify_email.py           # 可选 SMTP 邮件推送
│   ├── parsers/
│   │   ├── rss_journals.py       # 5 刊 RSS 解析
│   │   └── ssrn_marketing.py     # SSRN HTML 抓取（P2）
│   └── scraper/
│       ├── abstract.py           # 摘要抓取协调器（按 publisher 分发）
│       ├── sage.py               # Sage Crossref → S2
│       ├── informs.py            # INFORMS Crossref → Playwright/Scrapling → S2 + MktSci 缓存
│       ├── informs_page.py       # INFORMS 原文页完整摘要提取
│       ├── springer.py           # Springer HTML 抓取
│       └── _semantic_scholar.py  # S2 API 共享限速客户端
├── data/
│   ├── seen_dois.json            # DOI 注册表
│   └── mktsci_abstracts.json     # MktSci 完整摘要缓存
├── output/
│   └── YYYY-MM-DD.md            # 日报输出
├── tests/
│   ├── test_abstract_processing.py
│   ├── test_date_filter.py
│   ├── test_filter_mngsci.py
│   ├── test_informs_scraper.py
│   ├── test_llm.py
│   ├── test_relevance.py
│   ├── test_render.py
│   └── conftest.py
├── .env.example                  # LLM 配置模板
├── requirements.txt
├── run.sh                        # 本地快捷入口，调用 venv/bin/python -m src.fetch
└── README.md
```

### 9.1 文件职责速查

| 文件 | 职责 |
|------|------|
| `src/config.py` | 期刊、路径、LLM、限速和批量参数 |
| `src/fetch.py` | 管线主入口，编排 10 步流程 |
| `src/parsers/rss_journals.py` | 5 刊 RSS 元数据提取 |
| `src/parsers/ssrn_marketing.py` | SSRN Working Papers HTML 抓取（P2） |
| `src/scraper/abstract.py` | 摘要抓取调度器，按 publisher 分发 |
| `src/scraper/sage.py` | Sage/Crossref 摘要获取 |
| `src/scraper/informs.py` | INFORMS 摘要、`accepted_by`、MktSci 缓存和 pending 队列 |
| `src/scraper/informs_page.py` | INFORMS 原文页完整摘要提取 |
| `src/scraper/springer.py` | Springer/QME 摘要获取 |
| `src/scraper/_semantic_scholar.py` | Semantic Scholar API 兜底和共享限速 |
| `src/dedup.py` | DOI 去重、seen 注册表、日期窗口、relevance-first 截断排序 |
| `src/filter_mngsci.py` | Management Science marketing 过滤 |
| `src/relevance.py` | Quant relevance 打分，保护 LLM/recommendation/pricing/platform 等论文 |
| `src/translate.py` | 标题翻译 |
| `src/abstract.py` | 一句话总结与完整中文翻译 |
| `src/llm.py` | DeepSeek/Ollama 统一 LLM 客户端 |
| `src/render.py` | Markdown 渲染与保存 |
| `src/enrich_mktsci.py` | 手动补充 MktSci 完整摘要缓存 |
| `src/process_pending.py` | 输出待补 MktSci DOI 和原文 URL |
| `src/notify_email.py` | GitHub Actions 可选 SMTP 邮件发送 |

### 9.2 格式与行为定制入口

| 需求 | 修改位置 |
|------|----------|
| 日报整体布局 | `src/render.py` → `render_markdown()` |
| 单篇论文格式 | `src/render.py` → `_render_paper()` |
| 作者显示规则 | `src/render.py` → `_format_authors()` |
| 元数据标签 | `src/render.py` → `_format_tags()` |
| TOC 生成 | `src/render.py` → `_build_toc()` |
| 期刊板块标题 | `src/render.py` → `_get_section_title()` |
| 标题翻译 prompt | `src/translate.py` → `TRANSLATE_SYSTEM` |
| 一句话总结/完整翻译 prompt | `src/abstract.py` → `ONE_LINER_SYSTEM` / `ABSTRACT_ZH_SYSTEM` |
| LLM 后端优先级 | `src/llm.py` → `chat_json()` / `chat_text()` |
| MktSci 完整摘要补抓 | `src/scraper/informs.py` / `src/scraper/informs_page.py` |

---

## 10. 非功能需求

### 10.1 性能

| 场景 | 目标 | 说明 |
|---|---|---|
| 常规增量（≤ 10 篇候选）| < 5 分钟 | 含 LLM（Ollama） |
| 异常增量（11~50 篇候选）| < 10 分钟 | 标题 batch；摘要逐篇处理 |
| 首跑 / 冷启动 | 推荐先 `--dry-run` | 验证 RSS 元数据和截断候选 |

- 每日最大候选数：50 篇，relevance-first 截断
- 摘要抓取串行，间隔 ≥ 2 秒
- LLM batch 大小：标题翻译 5；摘要总结与完整翻译逐篇处理

### 10.2 可靠性

- 单篇摘要抓取失败不阻塞管线
- LLM 不可用时走降级模式（字段留空，不崩溃）
- 其他运行时异常：保留论文、标记缺失、记录日志、继续下一篇
- `--dry-run` 模式验证 RSS 元数据和 relevance 截断候选

### 10.3 可维护性

- 每个出版商独立 scraper 模块
- 新增同出版商期刊：仅需 `config.py` 一行配置
- 新增新出版商：加一个 ~30 行 scraper 文件 + 注册到 `abstract.py`

---

## 11. 实施优先级

| 优先级 | 模块 | 状态 | 说明 |
|--------|------|------|------|
| P0 | RSS 解析 + 元数据提取 | ✅ | 5 刊 RSS → Paper dict，双日期模型 |
| P0 | seen/date 预过滤 + 截断 | ✅ | 日期窗口 + 50 篇 relevance-first 排序 |
| P0 | 摘要抓取 | ✅ | Crossref → Playwright/Scrapling 原文页补抓 → S2，MktSci 缓存 |
| P0 | MngSci → Marketing 过滤 | ✅ | accepted_by 主导 + 关键词比分兜底 |
| P0 | LLM 标题翻译 + 双层摘要 | ✅ | DeepSeek → Ollama 回落，title_zh + one_line + abstract_zh |
| P0 | Markdown 渲染 + seen 注册 | ✅ | 8 行 + details 格式，TOC，commit seen_dois |
| P0 | GitHub Actions 调度 | ⚠️ | `daily.yml` 已配置，待触发验证 |
| P1 | GitHub Pages 静态站点 | ❌ | 从 `output/*.md` 构建多页归档 |
| P1 | Coze Bot Webhook 推送 | ❌ | 管线完成后 POST → 飞书/企微 |
| P1 | 邮件推送 | ⚠️ | `src/notify_email.py` 基础实现；需 SMTP secrets |
| P1 | MngSci DOM department 检测 | ❌ | INFORMS 详情页解析 |
| P2 | SSRN Working Papers | ⚠️ | 解析器就绪（publisher/online_date/coverdate 已补全），真实网络环境未验证 |

---

## 12. 验收标准

### 12.1 元数据正确性

- [ ] 每篇论文有 `title`、`authors`（列表）、`doi`、`journal`
- [ ] 日期字段含 `online_date` 和 `coverdate`
- [ ] Sage/INFORMS 论文的 `volume`/`issue` 从 RSS 提取

### 12.2 摘要质量

- [ ] 所有期刊的摘要通过 Crossref/S2 三级回退获取
- [ ] MktSci 优先通过缓存或 Playwright/Scrapling 原文页补抓获取完整摘要
- [ ] 摘要抓取失败标记 `[摘要缺失]`，不阻塞管线
- [ ] `abstract_missing=True` 时即使无摘要也渲染 `<details>` + 标记

### 12.3 日期过滤

- [ ] 过期论文（`online_date` < 窗口起点）不出现
- [ ] AiA 论文（无 coverdate 但有 updated）不被误过滤
- [ ] 无日期论文保守保留

### 12.4 去重与状态持久化

- [ ] 同 DOI 不在多天内重复出现
- [ ] `seen_dois.json` 成功后更新，失败不更新
- [ ] Push 前 `git pull --rebase`，失败重试
- [ ] Workflow 含 `concurrency: daily-run`

### 12.5 MngSci 过滤

- [ ] 通过 Crossref `accepted_by` 识别 marketing 部门
- [ ] `accepted_by` 不可用时以关键词比分兜底（pos-neg ≥ 2）
- [ ] 不区分 confirmed/[uncertain] 两级

### 12.6 日报格式

- [ ] 输出 `output/YYYY-MM-DD.md`
- [ ] 标题 `# Quant Marketing Daily — YYYY-MM-DD`
- [ ] 8 行 + `<details>` 折叠格式
- [ ] 含 TOC 目录
- [ ] 英文标题后紧跟中文译名
- [ ] 折叠区内含英文摘要 + 中文翻译
- [ ] 无新论文时生成空日报

### 12.7 LLM 集成

- [ ] `.env` 文件配置 API Key（`python-dotenv` 加载）
- [ ] DeepSeek 优先，不可用时回落 Ollama
- [ ] LLM 全不可用时降级（字段留空，不崩溃）

### 12.8 测试

- [ ] `venv/bin/python -m pytest -q` 通过（当前 55/55）
- [ ] 日期过滤有边界测试
- [ ] MngSci 过滤有 fixture 测试
- [ ] 渲染格式有 mock 测试
- [ ] Quant relevance 有 LLM/recommendation 和 behavioral 降权测试
- [ ] LLM JSON 清理、摘要串块防护、INFORMS 页面解析有回归测试

---

## 附录 A：与 v2 规格书的主要变化

| 领域 | v2 (`project_spec.md` v2.4) | v3.1（当前） | 变化原因 |
|------|------------------------------|-----------|----------|
| 管线步骤 | 7 步 | 10 步 | LLM 新增翻译+双层摘要，各独立成步 |
| 摘要来源 | 出版商 HTML 直接抓取 | Crossref JSON + Playwright/Scrapling 补抓 + S2 | MktSci Crossref 摘要过短且 INFORMS 有 Turnstile |
| MngSci 分级 | confirmed / [uncertain] 两级 | 单一 Marketing 板块 | accepted_by 信号可靠，uncertain 无展示价值 |
| 日报标题 | "Quant Marketing Today" | "Quant Marketing Daily" | Daily 更准确 |
| 日报格式 | 5 行软换行 | 8 行 + details 折叠 + TOC | 信息密度更高 |
| 摘要 Prompt | 单一 2-3 句 | 双层：一句话 + 完整翻译 | 列表 + 详情的不同需求 |
| LLM 后端 | DeepSeek 唯一 | DeepSeek → Ollama 回落 | 本地化，无 Key 也能跑 |
| MngSci 过滤位置 | 摘要抓取前 | 摘要抓取后、标题翻译前 | 避免浪费翻译和摘要生成资源 |
| 截断排序 | 三级（日期+优先级+标题） | 有日期 → quant relevance → 期刊优先级 → 日期 → MngSci 营销 tie-breaker | 防核心 quant paper 被 behavioral paper 挤出 |

---

## 附录 B：扩展性 — 新增期刊/出版商

### 同出版商

在 `config.py` 加一行：

```python
"JCR": {
    "name": "Journal of Consumer Research",
    "rss": "https://journals.sagepub.com/action/showFeed?jc=jcra&type=etoc&feed=rss",
    "publisher": "Sage",
    "needs_filter": False,
},
```

**零新代码**，现有 `scraper/sage.py` 自动处理。

### 新出版商

在 `scraper/` 下新增模块，然后在 `abstract.py` 注册。核心管线（`fetch.py`）不动。
