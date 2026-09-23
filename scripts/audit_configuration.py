"""审计 uPil 环境模板或指定环境文件，不输出任何敏感配置值。"""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.app.configuration.audit import audit_env_file, audit_project_templates


def main() -> int:
    """执行配置审计；发现问题返回非零状态，便于接入 CI。"""

    parser = argparse.ArgumentParser(description="审计 uPil 配置键和能力依赖")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="可选的环境文件；省略时审计仓库标准模板",
    )
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    if args.paths:
        issues = []
        for raw_path in args.paths:
            path = raw_path if raw_path.is_absolute() else project_root / raw_path
            issues.extend(audit_env_file(path))
    else:
        issues = audit_project_templates(project_root)

    if not issues:
        print("配置审计通过：未发现废弃键、未知键或能力依赖缺失。")
        return 0
    for issue in issues:
        try:
            display_path = issue.path.relative_to(project_root)
        except ValueError:
            display_path = issue.path
        print(f"{display_path}: {issue.key}: {issue.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
