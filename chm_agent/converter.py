from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.parse import quote, unquote, urlsplit


class ConversionError(RuntimeError):
    pass


@dataclass
class Page:
    source: str
    title: str
    markdown: str


@dataclass
class Chunk:
    id: str
    title: str
    source: str
    file: str
    chars: int


@dataclass
class ConversionResult:
    output: Path
    page_count: int
    chunk_count: int


SKIP_SUFFIXES = {".hhc", ".hhk", ".hhp"}
HTML_SUFFIXES = {".html", ".htm", ".xhtml"}
ASSET_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".xlsx", ".xls", ".csv", ".tsv",
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".txt", ".json", ".xml",
    ".yaml", ".yml", ".ini", ".conf", ".properties", ".sql", ".sh", ".pem", ".crt",
}


class _DocumentParser(HTMLParser):
    """Small, dependency-free HTML to readable Markdown converter."""

    BLOCKS = {"p", "div", "section", "article", "header", "footer", "tr", "blockquote"}
    SKIP = {"script", "style", "svg", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._title = False
        self._skip_depth = 0
        self._pre = False
        self._href_stack: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        attrs_dict = dict(attrs)
        if tag == "title":
            self._title = True
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in self.BLOCKS:
            self.parts.append("\n\n")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "pre":
            self._pre = True
            self.parts.append("\n\n```text\n")
        elif tag == "code" and not self._pre:
            self.parts.append("`")
        elif tag == "a":
            self.parts.append("[")
            self._href_stack.append(attrs_dict.get("href"))
        elif tag in {"td", "th"}:
            self.parts.append(" | ")
        elif tag == "img":
            alt = attrs_dict.get("alt") or "图片"
            src = attrs_dict.get("src") or ""
            self.parts.append(f"![{alt}]({src})" if src else f"[{alt}]")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._title = False
        elif tag == "pre":
            self._pre = False
            self.parts.append("\n```\n\n")
        elif tag == "code" and not self._pre:
            self.parts.append("`")
        elif tag == "a":
            href = self._href_stack.pop() if self._href_stack else None
            self.parts.append(f"]({href})" if href else "]")
        elif tag in self.BLOCKS or tag.startswith("h") and len(tag) == 2:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._title:
            self.title_parts.append(data)
            return
        if self._pre:
            self.parts.append(data)
        else:
            self.parts.append(re.sub(r"\s+", " ", data))

    def result(self) -> tuple[str, str]:
        title = re.sub(r"\s+", " ", "".join(self.title_parts)).strip()
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return title, text


class _TocParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[tuple[str, str]] = []
        self._name = ""
        self._local = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "li":
            self._flush()
        if tag.lower() != "param":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        key, value = values.get("name", "").lower(), values.get("value", "")
        if key == "name":
            self._name = value.strip()
        elif key == "local":
            self._local = value.strip()

    def close(self) -> None:
        self._flush()
        super().close()

    def _flush(self) -> None:
        if self._local:
            self.entries.append((self._local, self._name))
        self._name = self._local = ""


def _decode(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig", errors="replace")
    head = data[:4096]
    match = re.search(br"charset\s*=\s*[\"']?([\w.-]+)", head, re.IGNORECASE)
    encodings = [match.group(1).decode("ascii", "ignore")] if match else []
    encodings.extend(["utf-8", "gb18030", "big5", "windows-1252"])
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            pass
    return data.decode("utf-8", errors="replace")


def _normal_source(value: str) -> str:
    path = unquote(urlsplit(value.replace("\\", "/")).path).lstrip("/")
    return str(PurePosixPath(path)).lower()


def _content_root(root: Path) -> Path:
    toc_files = sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".hhc")
    if toc_files:
        return toc_files[0].parent
    children = [path for path in root.iterdir() if path.name != "__MACOSX"]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return root


def _is_windows() -> bool:
    return os.name == "nt"


def _find_7z() -> str | None:
    for name in ("7z.exe", "7z"):
        executable = shutil.which(name)
        if executable:
            return executable

    seen: set[str] = set()
    for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        root = os.environ.get(variable)
        if not root or root.lower() in seen:
            continue
        seen.add(root.lower())
        candidate = Path(root) / "7-Zip" / "7z.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def _find_hh() -> str | None:
    executable = shutil.which("hh.exe") or shutil.which("hh")
    if executable:
        return executable
    windows_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if windows_root:
        candidate = Path(windows_root) / "hh.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def _run_extractor(command: list[str], name: str) -> None:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        errors="replace",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip() or f"退出码 {completed.returncode}"
        raise ConversionError(f"{name} 解包失败：{detail}")


def _extract(source: Path, destination: Path) -> Path:
    if source.is_dir():
        return _content_root(source)
    if not source.is_file():
        raise ConversionError(f"找不到输入：{source}")
    if source.suffix.lower() != ".chm":
        raise ConversionError("输入应为 .chm 文件或已解包目录")
    if not _is_windows():
        raise ConversionError("CHM 文件解包仅支持 Windows；也可以传入已经解包的目录")

    seven_zip = _find_7z()
    if seven_zip:
        _run_extractor([seven_zip, "x", "-y", f"-o{destination}", str(source)], "7-Zip")
    else:
        html_help = _find_hh()
        if not html_help:
            raise ConversionError("未找到 7z.exe，也无法找到 Windows 系统自带的 hh.exe")
        _run_extractor([html_help, "-decompile", str(destination), str(source)], "hh.exe")

    root = _content_root(destination)
    if not any(path.is_file() and path.suffix.lower() in HTML_SUFFIXES for path in root.rglob("*")):
        raise ConversionError("解包命令已结束，但没有找到 HTML 页面")
    return root


def _toc(root: Path) -> tuple[list[str], dict[str, str]]:
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() != ".hhc" or not path.is_file():
            continue
        parser = _TocParser()
        parser.feed(_decode(path.read_bytes()))
        parser.close()
        order, names = [], {}
        for local, name in parser.entries:
            key = _normal_source(local)
            if key and key not in names:
                order.append(key)
                names[key] = html.unescape(name)
        if order:
            return order, names
    return [], {}


def _pages(root: Path) -> list[Page]:
    order, toc_names = _toc(root)
    rank = {name: index for index, name in enumerate(order)}
    paths = [
        p for p in root.rglob("*")
        if p.is_file() and not p.is_symlink() and p.suffix.lower() in HTML_SUFFIXES
    ]
    paths.sort(key=lambda p: (rank.get(_normal_source(p.relative_to(root).as_posix()), 10**9), p.as_posix().lower()))
    pages: list[Page] = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        parser = _DocumentParser()
        try:
            parser.feed(_decode(path.read_bytes()))
            parser.close()
        except (OSError, ValueError) as exc:
            raise ConversionError(f"读取页面失败 {relative}：{exc}") from exc
        html_title, markdown = parser.result()
        title = toc_names.get(_normal_source(relative)) or html_title or path.stem
        if markdown and len(re.sub(r"[#*`\s-]", "", markdown)) >= 10:
            pages.append(Page(relative, title, markdown))
    return pages


def _safe_name(title: str, source: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", title.lower(), flags=re.UNICODE).strip("-")
    digest = hashlib.sha1(source.encode()).hexdigest()[:8]
    return f"{value[:60] or 'page'}-{digest}"


def _split(markdown: str, limit: int) -> Iterable[str]:
    if len(markdown) <= limit:
        yield markdown
        return
    paragraphs = re.split(r"\n{2,}", markdown)
    current: list[str] = []
    size = 0
    for paragraph in paragraphs:
        pieces = [paragraph[i : i + limit] for i in range(0, len(paragraph), limit)] or [""]
        for piece in pieces:
            extra = len(piece) + (2 if current else 0)
            if current and size + extra > limit:
                yield "\n\n".join(current)
                current, size = [], 0
            current.append(piece)
            size += len(piece) + (2 if len(current) > 1 else 0)
    if current:
        yield "\n\n".join(current)


def _rewrite_images(markdown: str, page_source: str) -> str:
    def replace(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2).strip()
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or target.startswith(("#", "/")):
            return match.group(0)
        resolved = PurePosixPath(page_source).parent.joinpath(unquote(parsed.path))
        parts: list[str] = []
        for part in resolved.parts:
            if part in {"", "."}:
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        if not parts:
            return match.group(0)
        suffix = f"#{parsed.fragment}" if parsed.fragment else ""
        asset_path = quote("/".join(parts), safe="/")
        return f"![{label}](../assets/{asset_path}{suffix})"

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace, markdown)


def _resolve_local_target(page_source: str, target: str) -> tuple[str, str] | None:
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or target.startswith(("#", "/")):
        return None
    resolved = PurePosixPath(page_source).parent.joinpath(unquote(parsed.path))
    parts: list[str] = []
    for part in resolved.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    if not parts:
        return None
    return _normal_source("/".join(parts)), parsed.fragment


def _rewrite_links(
    markdown: str,
    page_source: str,
    targets: dict[str, str],
    assets: dict[str, str],
) -> str:
    def replace(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2).strip()
        resolved = _resolve_local_target(page_source, target)
        if not resolved:
            return match.group(0)
        source_key, fragment = resolved
        destination = targets.get(source_key)
        if not destination:
            asset = assets.get(source_key)
            if not asset:
                return match.group(0)
            destination = f"../assets/{quote(asset, safe='/')}"
        suffix = f"#{fragment}" if fragment else ""
        return f"[{label}]({destination}{suffix})"

    return re.sub(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)", replace, markdown)


def _copy_assets(root: Path, output: Path) -> dict[str, str]:
    assets = output / "assets"
    copied: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in ASSET_SUFFIXES:
            continue
        relative = path.relative_to(root)
        destination = assets / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        relative_posix = relative.as_posix()
        copied[_normal_source(relative_posix)] = relative_posix
    return copied


def _write(
    output: Path,
    pages: list[Page],
    max_chars: int,
    assets: dict[str, str],
) -> list[Chunk]:
    docs = output / "docs"
    docs.mkdir(parents=True)
    chunks: list[Chunk] = []
    planned: list[tuple[Page, list[str], list[str]]] = []
    for page_number, page in enumerate(pages, 1):
        parts = list(_split(page.markdown, max_chars))
        base = _safe_name(page.title, page.source)
        filenames: list[str] = []
        for part_number, content in enumerate(parts, 1):
            suffix = f"-{part_number:02d}" if len(parts) > 1 else ""
            filenames.append(f"{page_number:04d}-{base}{suffix}.md")
        planned.append((page, parts, filenames))

    targets = {
        _normal_source(page.source): filenames[0]
        for page, _, filenames in planned
        if filenames
    }
    for page, parts, filenames in planned:
        for part_number, (content, filename) in enumerate(zip(parts, filenames), 1):
            heading = page.title + (f"（{part_number}/{len(parts)}）" if len(parts) > 1 else "")
            content = _rewrite_images(content, page.source)
            content = _rewrite_links(content, page.source, targets, assets)
            body = f"# {heading}\n\n> CHM 来源：`{page.source}`\n\n{content.strip()}\n"
            (docs / filename).write_text(body, encoding="utf-8")
            chunks.append(Chunk(
                id=f"doc-{len(chunks) + 1:05d}", title=heading, source=page.source,
                file=f"docs/{filename}", chars=len(content),
            ))
    return chunks


def _write_metadata(output: Path, source: Path, pages: list[Page], chunks: list[Chunk]) -> None:
    manifest = {
        "format": "chm-agent-docs/v1",
        "source": str(source),
        "pages": len(pages),
        "chunks": [asdict(chunk) for chunk in chunks],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    catalog = ["# 文档目录", "", f"共 {len(pages)} 个页面、{len(chunks)} 个可读分片。", ""]
    catalog.extend(f"- [{chunk.title}]({chunk.file}) — `{chunk.source}`" for chunk in chunks)
    (output / "CATALOG.md").write_text("\n".join(catalog) + "\n", encoding="utf-8")
    guide = """# Agent 阅读指南

这是从 CHM 转换得到的 Markdown 知识库。

## 推荐读取方式

1. 先读 `CATALOG.md`，了解主题和原始目录。
2. 回答问题前，用全文搜索定位关键词，例如：`rg -n -i '关键词' docs CATALOG.md`。
3. 打开命中的 `docs/*.md`；相关主题跨文件时同时读取相邻或同源分片。
4. 回答时引用 Markdown 文件名，并区分文档明确说明与自行推断。

`manifest.json` 提供机器可读的分片标题、来源、路径和字符数。本地图片保存在 `assets/` 中。
"""
    (output / "AGENT_GUIDE.md").write_text(guide, encoding="utf-8")


def convert(source: Path, output: Path, max_chars: int = 20_000, force: bool = False) -> ConversionResult:
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    if max_chars < 1_000:
        raise ConversionError("--max-chars 不能小于 1000")
    if source.is_dir() and (output == source or source in output.parents):
        raise ConversionError("输出目录不能位于输入目录内部")
    if output.exists():
        if not force:
            raise ConversionError(f"输出目录已存在：{output}（使用 --force 重建）")
        if output == source or output in source.parents:
            raise ConversionError("拒绝删除输入目录或其父目录")
        shutil.rmtree(output)
    output.mkdir(parents=True)

    try:
        with tempfile.TemporaryDirectory(prefix="chm-agent-") as temp:
            root = _extract(source, Path(temp))
            pages = _pages(root)
            if not pages:
                raise ConversionError("没有在文档中找到可读取的 HTML 页面")
            assets = _copy_assets(root, output)
            chunks = _write(output, pages, max_chars, assets)
            _write_metadata(output, source, pages, chunks)
    except Exception:
        if output.exists():
            shutil.rmtree(output)
        raise
    return ConversionResult(output, len(pages), len(chunks))
