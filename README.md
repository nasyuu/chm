# CHM Agent 文档工具

把体量很大的 CHM 产品文档转换为一套 Agent 可以直接全文检索、按需读取和引用的 Markdown 知识库。

输出内容包括：

- `AGENT_GUIDE.md`：告诉 Agent 如何检索和阅读
- `CATALOG.md`：保留 CHM 目录顺序的可读目录
- `docs/*.md`：清洗后的正文，过长页面会自动分片
- `assets/`：正文引用的本地图片及 ZIP、XLSX、PDF 等附件
- `manifest.json`：供程序或 Agent 使用的结构化索引

## 使用

本工具面向 Windows。解包时优先使用 7-Zip；程序会依次检查：

- PATH 中的 `7z.exe`
- `%ProgramFiles%\7-Zip\7z.exe`
- `%ProgramW6432%\7-Zip\7z.exe`
- `%ProgramFiles(x86)%\7-Zip\7z.exe`

如果没有安装 7-Zip，程序会自动使用 Windows 系统自带的 `%SystemRoot%\hh.exe`
执行 `-decompile`。不需要单独安装其他 CHM 解包工具。

转换文档：

```powershell
uv run chm-agent path/to/product.chm -o product-docs
```

也可以直接转换一个已经解包、包含 HTML 的目录：

```powershell
uv run chm-agent path/to/extracted-chm -o product-docs
```

让 Agent 使用时，可以直接说：

> 请先阅读 `product-docs/AGENT_GUIDE.md`，再根据文档回答我的问题。

默认每个分片最多 20,000 字符。可以用 `--max-chars 12000` 调整；输出目录已存在时，只有显式传入 `--force` 才会重建。

## 安装文档分析提示词

项目提供了面向复杂安装分支的提示词，包括场景地图、局点安装执行手册、安装前检查、
文档审计和故障定位，参见 [`prompts/installation-prompts.md`](prompts/installation-prompts.md)。

## 场景化安装技能

[`skills/plan-product-installation`](skills/plan-product-installation/SKILL.md) 用于根据物理机、
虚拟机、全新安装或追加部署等指定场景生成带文档依据的安装执行手册。使用示例：

```text
使用 $plan-product-installation 为 Smart Decision 生成物理机全新安装方案。
```

该技能会先确认会改变安装路径的场景条件，再读取对应分支，避免混用物理机、虚拟机、
全新安装和追加部署步骤。

## 安装场景模型

`installation-models/<产品>/<版本>/` 将场景轴、组合约束、原子步骤、主路线和文档证据
作为版本化资产保存。当前包含 Smart Decision 7.3.0 的第一版模型。

查看支持的场景字段和路线：

```powershell
uv run chm-agent scenarios installation-models/smart-decision/7.3.0
```

检查模型结构以及所有文档来源：

```powershell
uv run chm-agent validate-model installation-models/smart-decision/7.3.0 `
  --knowledge-base smart-decision-7.3.0-agent-docs
```

编译物理机全新安装执行手册：

```powershell
uv run chm-agent plan installation-models/smart-decision/7.3.0 `
  --set installation_nature=new `
  --set deployment_carrier=physical `
  --set topology=standard `
  --set data_platform=external_fi `
  --set data_platform_access=admin
```

信息不足时输出稳定主流程、条件步骤和阻断项；组合违反产品约束时返回错误，避免 Agent
混合不兼容的安装分支。完整场景档案也可以通过 `--profile site-profile.json` 传入。

## 直接运行

项目本身只使用 Python 标准库。Python 3.9+ 可直接运行：

```powershell
py main.py path/to/product.chm -o product-docs
```
