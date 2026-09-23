"""执行离线多轮状态评测，不调用任何真实外部服务。"""

from __future__ import annotations

import sys
from pathlib import Path

# 支持既用 ``python -m scripts.evaluate_multiturn_state``，也能直接执行本文件。
# 这里只调整本地模块查找路径，不读取环境密钥或连接任何外部服务。
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.intent_evaluation.multiturn import evaluate_multiturn_cases
from scripts.intent_evaluation.multiturn_cases import MULTITURN_CASES
from scripts.intent_evaluation.reporting import format_multiturn_report


def main() -> int:
    """输出指标，并以退出码表达所有结构化期望是否通过。"""

    report = evaluate_multiturn_cases(MULTITURN_CASES)
    print(format_multiturn_report(report))
    return 0 if not report.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
