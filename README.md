# CHM Agent Docs

把体量很大的 CHM 产品文档转换为一套 Agent 可以直接全文检索、按需读取和引用的 Markdown 知识库。

输出内容包括：

- `AGENT_GUIDE.md`：告诉 Agent 如何检索和阅读
- `CATALOG.md`：保留 CHM 目录顺序的可读目录
- `docs/*.md`：清洗后的正文，过长页面会自动分片
- `assets/`：正文引用的本地图片及 ZIP、XLSX、PDF 等附件
- `manifest.json`：供程序或 Agent 使用的结构化索引

## 使用

CHM 解包需要系统中安装 `7zz`、`7z`、`extract_chmLib` 或 `unar` 之一。macOS 推荐：

```bash
brew install sevenzip
```

转换文档：

```bash
uv run chm-agent path/to/product.chm -o product-docs
```

也可以直接转换一个已经解包、包含 HTML 的目录：

```bash
uv run chm-agent path/to/extracted-chm -o product-docs
```

让 Agent 使用时，可以直接说：

> 请先阅读 `product-docs/AGENT_GUIDE.md`，再根据文档回答我的问题。

默认每个分片最多 20,000 字符。可以用 `--max-chars 12000` 调整；输出目录已存在时，只有显式传入 `--force` 才会重建。

## 安装文档分析 Prompt

项目提供了面向复杂安装分支的 Prompt，包括场景地图、局点 Runbook、安装前检查、
文档审计和故障定位，参见 [`prompts/installation-prompts.md`](prompts/installation-prompts.md)。

## 无安装运行

项目本身只使用 Python 标准库。Python 3.9+ 可直接运行：

```bash
python3 main.py path/to/product.chm -o product-docs
```
