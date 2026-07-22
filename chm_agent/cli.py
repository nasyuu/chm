from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .converter import ConversionError, convert


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chm-agent",
        description="将 CHM 产品文档转换为 Agent 易于检索和阅读的 Markdown 知识库。",
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


def main(argv: list[str] | None = None) -> None:
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
