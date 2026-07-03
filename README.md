# Quant Marketing Daily

每日自动抓取 Quantitative Marketing 五大顶刊最新论文，生成中文摘要日报。

## 覆盖期刊

| 期刊 | 缩写 | 出版商 | 过滤策略 |
|------|------|--------|----------|
| Journal of Marketing | JM | Sage | 无（全刊营销） |
| Journal of Marketing Research | JMR | Sage | 无（全刊营销） |
| Marketing Science | MktSci | INFORMS | 无（全刊营销） |
| Quantitative Marketing and Economics | QME | Springer | 无（全刊营销） |
| Management Science (Marketing) | MngSci | INFORMS | **accepted_by + 关键词比分** |

> MngSci 是综合管理学期刊，含 Finance / OR / OB 等多部门论文。管线通过 Crossref `accepted_by` 字段识别 marketing 部门，不可用时以标题+摘要关键词比分兜底（pos-neg ≥ 2）。不再区分 `[uncertain]` 分级。

截断前会先按 quant relevance 保留更相关的论文，避免 consumer psychology / behavioral marketing 论文挤掉 pricing、platform、structural model、causal inference、LLM、recommendation 等方向的论文。期刊保留优先级为：MktSci → QME → MngSci → JMR → JM → SSRN。

## 日报预览

```markdown
# Quant Marketing Daily — 2026-07-02

_2026-06-01 ~ 2026-07-02 · 20 篇新论文 · 4 个来源_

## 目录
- [Journal of Marketing (X 篇)](#journal-of-marketing-x-篇)
...

---
## Journal of Marketing (1 篇)

- **Temporal Patterns of New Product Introductions and IPO Value**
  *新产品发布的时间模式与IPO价值*
  *Suyun Mah, Rebecca J. Slotegraaf, Girish Mallapragada*
  `2026-07` · `Vol.90(4)` · `doi:10.1177/00222429251382272`
  **AI 总结：** 结构模型分析IPO前发布节奏/分散度/不对称性组合显著提升估值。
  **原文链接：** [Source](https://doi.org/...)

  <details>
  <summary><b>展开详情</b></summary>

  **Abstract:** Full English abstract...
  **中文翻译：** 完整中文翻译...
  </details>
```

> 格式说明：8 行 + `<details>` 折叠。英文标题 + 中文译名 + 作者 + 元数据标签 + AI 一句话总结 + 原文链接。折叠区内含完整英文摘要和中文翻译。

## 架构

```
        ┌────────────────────────────┐
        │  [1] RSS 元数据发现（5 刊）  │
        └─────────────┬──────────────┘
                      ▼
        ┌────────────────────────────┐
        │  [2] DOI 标准化 + 去重      │
        └─────────────┬──────────────┘
                      ▼
        ┌────────────────────────────┐
        │  [3] seen + date 预过滤    │  ← 排除已推送 + 过期论文
        └─────────────┬──────────────┘
                      ▼
        ┌────────────────────────────┐
        │  [4] 候选池截断 + 相关性排序 │  ← 有日期 → quant relevance → 期刊优先级
        └─────────────┬──────────────┘
                      ▼
        ┌────────────────────────────┐
        │  [5] 摘要抓取               │  ← MktSci: 缓存 → Crossref → Playwright/Scrapling → S2
        └─────────────┬──────────────┘
                      ▼
        ┌────────────────────────────┐
        │  [6] MngSci → Marketing    │  ← accepted_by 主导 + 关键词比分（先过滤减成本）
        └─────────────┬──────────────┘
                      ▼
        ┌────────────────────────────┐
        │  [7] LLM 标题翻译           │  ← DeepSeek → Ollama 回落
        └─────────────┬──────────────┘
                      ▼
        ┌────────────────────────────┐
        │  [8] AI 双层摘要           │  ← 逐篇生成：一句话 + 完整中文翻译
        └─────────────┬──────────────┘
                      ▼
        ┌────────────────────────────┐
        │  [9] Markdown 日报渲染      │  ← 8 行 + details 折叠 + TOC
        └─────────────┬──────────────┘
                      ▼
        ┌────────────────────────────┐
        │  [10] seen_dois 写入 main   │  ← 仅成功时 commit
        └────────────────────────────┘
```

## 项目结构

```
quant-marketing-daily/
├── .github/workflows/daily.yml         # GitHub Actions 自动调度（UTC 1:00）
├── docs/
│   └── project_spec.md                 # 唯一规格与验收标准
├── src/
│   ├── __init__.py                     # 包初始化
│   ├── fetch.py                        # 主入口，10 步管线编排 + 前后诊断
│   ├── config.py                       # 期刊配置、LLM、时区、性能约束
│   │
│   ├── dedup.py                        # [2][3][4] DOI 去重 + 日期窗口 + seen + relevance-first 截断
│   ├── filter_mngsci.py                # [6] MngSci → Marketing 双策略过滤（accepted_by + 关键词比分）
│   ├── relevance.py                    # [4] Quant relevance 打分（LLM/recommendation 等）
│   ├── translate.py                    # [7] LLM 批量标题翻译（DeepSeek → Ollama 回落）
│   ├── abstract.py                     # [8] LLM 双层摘要（逐篇生成，避免串块）
│   ├── render.py                       # [9] Markdown 日报渲染（8 行 + details 折叠 + TOC）
│   │
│   ├── llm.py                          # 统一 LLM 客户端（三级回落，不可用时降级不崩溃）
│   ├── process_pending.py              # MktSci 待抓取队列诊断工具
│   ├── enrich_mktsci.py                # MktSci 完整摘要缓存管理 CLI
│   ├── notify_email.py                 # 可选 SMTP 邮件推送
│   │
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── rss_journals.py             # [1] 5 刊 RSS 解析（双日期模型）
│   │   └── ssrn_marketing.py           # SSRN working paper 爬取（P2）
│   └── scraper/
│       ├── __init__.py
│       ├── abstract.py                 # [5] 摘要抓取协调器，分派出版商 → 返回 (abstract, accepted_by)
│       ├── sage.py                     # Sage: Crossref → S2 三级抓取
│       ├── informs.py                  # INFORMS: Crossref/Playwright/Scrapling → S2 + MktSci 缓存 + accepted_by
│       ├── informs_page.py             # INFORMS 原文页完整摘要 HTML 提取
│       ├── springer.py                 # Springer HTML 抓取
│       └── _semantic_scholar.py        # S2 API 共享限速客户端
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_abstract_processing.py
│   ├── test_date_filter.py
│   ├── test_filter_mngsci.py
│   ├── test_informs_scraper.py
│   ├── test_llm.py
│   ├── test_relevance.py
│   └── test_render.py
├── data/
│   ├── seen_dois.json                  # DOI 注册表（须持久保留，step [10] commit）
│   ├── mktsci_abstracts.json           # MktSci 完整摘要缓存
│   └── pending_mktsci.json             # MktSci 待抓取 DOI 列表（运行时生成）
├── output/                             # 每日 Markdown 产出
├── .env.example                        # LLM 配置模板
├── requirements.txt
├── run.sh                              # 本地快捷入口
└── README.md
```

## 快速开始

### 1. 配置 LLM

```bash
cd quant-marketing-daily
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY=sk-xxx
```

LLM 优先级：**DeepSeek API → Ollama 本地 (qwen2.5:7b) → 降级（字段留空，不崩溃）**。

Ollama 配置：
```bash
# .env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
```

Marketing Science 完整摘要补抓：
```bash
# 默认：Playwright 持久化 profile → Scrapling 静态 fetch；失败则保留 Crossref/S2 结果并写入 pending_mktsci.json
INFORMS_PAGE_TIMEOUT_MS=25000
INFORMS_PW_HEADLESS=1

# 本地调试浏览器/stealth 模式时再打开，避免定时任务卡在 Cloudflare
INFORMS_USE_STEALTH=1
INFORMS_STEALTH_HEADLESS=0
```

### 2. 本地运行

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 首跑建议 dry-run：验证 RSS 元数据和截断候选，不写 seen_dois
python -m src.fetch --dry-run

# 确认无误后正式运行
python -m src.fetch

# 重建今天窗口内完整日报（忽略 seen_dois，不改 seen_dois）
python -m src.fetch --rebuild

# 等价快捷入口：自动使用项目内 venv
./run.sh --rebuild
```

### 3. GitHub Actions 自动部署

`.github/workflows/daily.yml` 已配置。在 Settings → Secrets → Actions 添加：

| Secret | 说明 |
|--------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com` |
| `SMTP_SERVER` | 可选，配置后发送邮件 |
| `SMTP_PORT` | 可选，默认 `587` |
| `SMTP_USERNAME` | 可选，SMTP 登录用户名 |
| `SMTP_PASSWORD` | 可选，SMTP 应用专用密码/授权码 |
| `SMTP_FROM` | 可选，默认等于 `SMTP_USERNAME` |
| `NOTIFY_EMAIL` | 可选，收件地址，多个用逗号分隔 |

调度：UTC 1:00（北京时间 09:00），cron `0 1 * * *`。已配置 `concurrency: daily-run` 防并发。

### 4. 无 GitHub Actions 时

```bash
# crontab — 每天早 9:00
0 9 * * * cd /path/to/quant-marketing-daily && ./venv/bin/python -m src.fetch
```

## CLI 参数

```
python -m src.fetch [--dry-run] [--rebuild] [--include-ssrn]
```

| Flag | 说明 |
|------|------|
| `--dry-run` | 仅 RSS 发现 + 去重 + 日期过滤 + relevance 截断，不抓摘要、不写 seen_dois |
| `--rebuild` | 忽略 `seen_dois` 重建当日窗口日报，不写 seen_dois |
| `--include-ssrn` | 启用 SSRN Working Paper 抓取（P2，默认关闭） |

## 依赖

| 包 | 用途 |
|----|------|
| Python | ≥ 3.10 |
| feedparser | RSS 解析 |
| requests | HTTP 请求（Crossref + S2） |
| beautifulsoup4 + lxml | HTML 解析 |
| scrapling[fetchers] | INFORMS / MktSci 静态原文页补抓 |
| playwright | INFORMS / MktSci 持久化浏览器 profile 补抓 |
| openai | DeepSeek 兼容 API |
| python-dotenv | `.env` 配置加载 |
| pytest | 测试运行 |

## 文档

- 本 README 即项目主文档（含架构、项目结构、快速开始、CLI 参数等）
- [docs/project_spec.md](docs/project_spec.md) — 唯一规格与验收标准
- `.env.example` — LLM 配置模板
