from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .converter import ConversionError, convert
from .installation_model import (
    ModelError,
    compile_plan,
    load_model,
    render_plan_markdown,
    validate_model,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chm-agent",
        description="将 CHM 产品文档转换为 Agent 易于检索和阅读的 Markdown 知识库。",
        epilog=(
            "安装模型命令：chm-agent scenarios <model>；"
            "chm-agent validate-model <model>；chm-agent plan <model> --set FIELD=VALUE"
        ),
    )
    parser.add_argument("source", type=Path, help="CHM 文件，或已经解包的 CHM 目录")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="输出目录（默认：<CHM文件名>-agent-docs）",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=20_000,
        help="单个 Markdown 分片的最大字符数（默认：20000）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="删除并重建已存在的输出目录",
    )
    return parser


def _command_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chm-agent",
        description="转换 CHM，或根据版本化安装模型编译场景安装执行手册。",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    scenarios = commands.add_parser("scenarios", help="显示模型支持的场景字段和安装路线")
    scenarios.add_argument("model", type=Path, help="安装模型目录")

    validate = commands.add_parser("validate-model", help="校验安装模型、约束、步骤和文档来源")
    validate.add_argument("model", type=Path, help="安装模型目录")
    validate.add_argument("--knowledge-base", type=Path, help="同时检查来源文件是否存在")

    plan = commands.add_parser("plan", help="根据场景条件生成安装执行手册")
    plan.add_argument("model", type=Path, help="安装模型目录")
    plan.add_argument("--profile", type=Path, help="JSON 格式的局点场景档案")
    plan.add_argument(
        "--set",
        dest="values",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help="设置场景字段；列表值使用英文逗号分隔，可重复",
    )
    plan.add_argument("-o", "--output", type=Path, help="写入文件；默认输出到终端")
    plan.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser


def _profile_value(raw: str) -> str | list[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values if len(values) > 1 else values[0] if values else ""


def _load_profile(path: Path | None, overrides: list[str]) -> dict[str, object]:
    profile: dict[str, object] = {}
    if path:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ModelError(f"找不到场景档案：{path}") from exc
        except json.JSONDecodeError as exc:
            raise ModelError(f"场景档案 JSON 格式错误：{exc}") from exc
        if not isinstance(loaded, dict):
            raise ModelError("场景档案必须是 JSON 对象")
        profile.update(loaded)
    for item in overrides:
        if "=" not in item:
            raise ModelError(f"--set 格式应为 FIELD=VALUE：{item}")
        field, raw = item.split("=", 1)
        if not field.strip():
            raise ModelError(f"--set 缺少字段名：{item}")
        profile[field.strip()] = _profile_value(raw)
    return profile


def _render_scenarios(model_path: Path) -> str:
    model = load_model(model_path)
    lines = [f"# {model.metadata['product']} {model.metadata['version']} 安装场景", "", "## 场景字段", ""]
    for field, axis in model.axes.items():
        values = axis.get("values", {})
        rendered = "、".join(f"`{key}`（{label}）" for key, label in values.items())
        lines.append(f"- `{field}` / {axis.get('label', field)}：{rendered}")
    lines.extend(["", "## 安装路线", ""])
    for route in model.routes:
        conditions = "，".join(f"`{key}={value}`" for key, value in route.get("when", {}).items())
        lines.append(f"- `{route['id']}`：{route['title']} — {conditions}")
    return "\n".join(lines) + "\n"


def _run_command(argv: list[str]) -> None:
    args = _command_parser().parse_args(argv)
    try:
        if args.command == "scenarios":
            print(_render_scenarios(args.model), end="")
            return
        if args.command == "validate-model":
            model = load_model(args.model)
            errors = validate_model(model, args.knowledge_base)
            if errors:
                for error in errors:
                    print(f"错误：{error}", file=sys.stderr)
                raise SystemExit(2)
            print(f"模型有效：{model.metadata['product']} {model.metadata['version']}")
            print(f"路线 {len(model.routes)} 条，步骤 {len(model.steps)} 个，约束 {len(model.constraints)} 条")
            return

        model = load_model(args.model)
        profile = _load_profile(args.profile, args.values)
        plan = compile_plan(model, profile)
        content = (
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
            if args.format == "json"
            else render_plan_markdown(plan)
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(content, encoding="utf-8")
            print(f"已生成：{args.output.resolve()}")
        else:
            print(content, end="")
        if plan["status"] == "invalid":
            raise SystemExit(2)
    except ModelError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"scenarios", "validate-model", "plan"}:
        _run_command(argv)
        return
    args = build_parser().parse_args(argv)
    output = args.output or Path(f"{args.source.stem}-agent-docs")
    try:
        result = convert(args.source, output, args.max_chars, force=args.force)
    except ConversionError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    print(f"已转换 {result.page_count} 个页面、{result.chunk_count} 个分片")
    print(f"知识库：{result.output.resolve()}")
    print(f"阅读入口：{(result.output / 'AGENT_GUIDE.md').resolve()}")
