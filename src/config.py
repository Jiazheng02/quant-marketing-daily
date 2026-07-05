"""
Quantitative Marketing Daily — 配置模块。

时区约定：所有日期计算以 Asia/Shanghai (UTC+8) 为准。
GitHub Actions schedule 使用 `timezone: Asia/Shanghai`，北京时间 03:07 生成日报并发送邮件。

API 密钥通过 .env 文件配置（由 python-dotenv 自动加载）。
复制 .env.example → .env 并填入实际密钥即可。
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# 自动加载项目根目录下的 .env
_env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(_env_path)

# ---------------------------------------------------------------------------
# 时区
# ---------------------------------------------------------------------------
TZ = ZoneInfo("Asia/Shanghai")


def today_str() -> str:
    """返回 Asia/Shanghai 时区下的今日日期 YYYY-MM-DD。"""
    return datetime.now(TZ).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 期刊配置
# ---------------------------------------------------------------------------
JOURNALS = {
    "JM": {
        "name": "Journal of Marketing",
        "rss": "https://journals.sagepub.com/action/showFeed?jc=jmxa&type=etoc&feed=rss",
        "publisher": "Sage",
        "needs_filter": False,
        "priority": 5,  # 截断排序用（越小越优先）
    },
    "JMR": {
        "name": "Journal of Marketing Research",
        "rss": "https://journals.sagepub.com/action/showFeed?jc=mrja&type=etoc&feed=rss",
        "publisher": "Sage",
        "needs_filter": False,
        "priority": 4,
    },
    "MktSci": {
        "name": "Marketing Science",
        "rss": "https://pubsonline.informs.org/action/showFeed?jc=mksc&type=etoc&feed=rss",
        "publisher": "INFORMS",
        "needs_filter": False,
        "priority": 1,
    },
    "QME": {
        "name": "Quantitative Marketing and Economics",
        "rss": "https://link.springer.com/search.rss?facet-content-type=Article&facet-journal-id=11129",
        "publisher": "Springer",
        "needs_filter": False,
        "priority": 2,
    },
    "MngSci": {
        "name": "Management Science",
        "rss": "https://pubsonline.informs.org/action/showFeed?jc=mnsc&type=etoc&feed=rss",
        "publisher": "INFORMS",
        "needs_filter": True,
        "priority": 3,
    },
    "SSRN": {
        "name": "SSRN Working Papers",
        "rss": None,  # SSRN 无 RSS，走 HTML 抓取
        "publisher": "SSRN",
        "needs_filter": False,
        "priority": 6,
    },
}

# 渲染顺序：quant-first，避免 behavioral-heavy 全刊营销内容压过核心 quant 论文。
JOURNAL_ORDER = ["MktSci", "QME", "MngSci", "JMR", "JM", "SSRN"]

# ---------------------------------------------------------------------------
# 出版商 → 详情页 URL 模板
# ---------------------------------------------------------------------------
PUBLISHER_DETAIL_URL = {
    "Sage": "https://journals.sagepub.com/doi/abs/{doi}",
    "INFORMS": "https://pubsonline.informs.org/doi/abs/{doi}",
    "Springer": None,  # Springer 用 RSS 中的 <link> 字段
}

# ---------------------------------------------------------------------------
# RSS 抓取上限
# ---------------------------------------------------------------------------
RSS_MAX_ENTRIES = {
    "JM": 40,
    "JMR": 40,
    "MktSci": 40,
    "QME": 20,
    "MngSci": 60,  # 大刊，~45 篇/期
}

# ---------------------------------------------------------------------------
# SSRN（P2，默认关闭）
# ---------------------------------------------------------------------------
SSRN_URL = "https://papers.ssrn.com/sol3/JELJOUR_Results.cfm?form_name=journalBrowse&journal_id=458558"

# ---------------------------------------------------------------------------
# DeepSeek API（优先）
# ---------------------------------------------------------------------------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# ---------------------------------------------------------------------------
# Ollama 本地 LLM（DeepSeek 不可用时的回落）
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "300"))

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
SEEN_DOIS_FILE = os.path.join(DATA_DIR, "seen_dois.json")

# ---------------------------------------------------------------------------
# 性能约束
# ---------------------------------------------------------------------------
MAX_CANDIDATE_PAPERS = 50       # 每日最大候选数（Crossref 回退后需更大容量）
SCRAPE_DELAY_SEC = 2.0          # 请求间隔
SCRAPE_TIMEOUT_SEC = 15         # 单次超时
SCRAPE_RETRIES = 2              # 重试次数
TRANSLATION_BATCH_SIZE = 5      # 标题翻译批量大小（qwen2.5:7b 每篇 ~10s，batch=5 约 50s）
