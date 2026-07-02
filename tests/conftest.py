"""
Pytest 配置 — 将项目根加入 sys.path。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
