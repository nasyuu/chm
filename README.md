# CHM Agent 文档工具

本项目用于把篇幅庞大、目录层级复杂的 CHM 产品文档，转换成 Agent 可以检索、按需读取和准确引用的 Markdown 知识库；同时将复杂安装指南中的场景条件、组合约束和安装步骤沉淀为版本化模型，帮助 Agent 针对具体局点生成完整、可追溯的端到端安装执行手册。

项目目前重点解决以下问题：

- CHM 文档无法直接被大多数 Agent 稳定读取和全文检索；
- 文档过大，无法一次性放入上下文；
- 安装指南包含物理机、虚拟机、全新安装、追加部署等大量交叉分支；
- 仅靠关键词检索容易混合不兼容的安装步骤；
- 安装要求散落在概述、限制、操作步骤、附录和外部资料中，难以形成完整流程；
- 不同产品版本的安装组合和文档依据需要持续维护、评审和复用。

## 整体方案

项目由“文档知识库”和“安装场景模型”两层组成。

```text
CHM 产品文档
    ↓ 解包、解析目录、清洗正文、重写链接、自动分片
Markdown 知识库
    ↓ 提取场景轴、组合约束、主路线、原子步骤和来源
版本化安装模型
    ↓ 根据局点场景进行确定性编译
候选安装步骤
    ↓ Agent 读取所选步骤对应的 Markdown 证据并补充细节
端到端安装执行手册、检查表、风险和待确认项
```

### 1. 将 CHM 转换为 Agent 知识库

转换工具保留原 CHM 的目录顺序和页面关系，并输出：

- `AGENT_GUIDE.md`：告诉 Agent 如何检索、阅读和引用知识库；
- `CATALOG.md`：保留 CHM 目录顺序的可读目录；
- `docs/*.md`：清洗后的正文，过长页面会自动分片；
- `assets/`：正文引用的图片及 ZIP、XLSX、PDF 等附件；
- `manifest.json`：供程序或 Agent 使用的结构化索引。

Agent 不需要一次读取全部文档，可以先查看目录，再使用关键词定位章节，最后只打开与当前问题有关的页面。

### 2. 将安装组合沉淀为版本化模型

`installation-models/<产品>/<版本>/` 保存某个产品版本的安装知识：

- `model.json`：场景字段及其允许值，例如部署载体、安装性质、组网和数据库；
- `constraints.json`：不允许或必须补充信息的组合约束；
- `routes.json`：物理机、虚拟机、追加部署等端到端主路线；
- `steps.jsonl`：可复用的原子安装步骤、适用条件和文档来源；
- `model.lock.json`：来源 CHM、知识库和模型版本信息。

场景编译器先根据明确规则判断组合，再选择和排序步骤。这样可以避免 Agent 因关键词相似而把物理机与虚拟机、全新安装与追加部署、SSL 与非 SSL 等互斥步骤混在一起。

### 3. 使用 Agent 补充操作细节

编译器负责回答“这个场景应该走哪条路线、包含哪些步骤”；Agent 负责打开这些步骤引用的 Markdown 页面，补充命令、参数、前置条件、注意事项、预期结果和验证方法。

项目提供两个可复用入口：

- [场景化安装技能](skills/plan-product-installation/SKILL.md)：指导 Agent 先编译场景，再读取证据并生成安装执行手册；
- [安装文档提示词集](prompts/installation-prompts.md)：用于场景地图、局点安装方案、安装前检查、文档审计和故障分析。

## 运行环境

- Windows；
- Python 3.9 或更高版本；
- 推荐安装 [uv](https://docs.astral.sh/uv/)；
- 推荐安装 7-Zip。

处理 CHM 文件时，程序优先使用 7-Zip，并依次检查：

- PATH 中的 `7z.exe`；
- `%ProgramFiles%\7-Zip\7z.exe`；
- `%ProgramW6432%\7-Zip\7z.exe`；
- `%ProgramFiles(x86)%\7-Zip\7z.exe`。

如果没有安装 7-Zip，程序会使用 Windows 自带的 `%SystemRoot%\hh.exe` 执行 `-decompile`。项目不考虑 Linux 环境下的 CHM 解包。

## 快速开始

### 第一步：转换 CHM 文档

在项目目录执行：

```powershell
uv run chm-agent "D:\docs\product.chm" -o product-agent-docs
```

也可以转换一个已经解包、包含 HTML 文件的目录：

```powershell
uv run chm-agent "D:\docs\product-html" -o product-agent-docs
```

默认每个 Markdown 分片最多 20,000 个字符。可以使用 `--max-chars` 调整：

```powershell
uv run chm-agent "D:\docs\product.chm" -o product-agent-docs --max-chars 12000
```

输出目录已存在时，工具默认停止，避免覆盖已有知识库。确认需要重建时使用 `--force`：

```powershell
uv run chm-agent "D:\docs\product.chm" -o product-agent-docs --force
```

### 第二步：让 Agent 阅读知识库

对于一般的产品文档问答，可以直接告诉 Agent：

```text
请先阅读 product-agent-docs/AGENT_GUIDE.md，使用 CATALOG.md 定位相关章节，
只读取与问题有关的 Markdown 页面，并为关键结论引用来源文件。

问题：<填写具体问题>
```

### 第三步：查看支持的安装场景

以项目内置的 Smart Decision 7.3.0 模型为例：

```powershell
uv run chm-agent scenarios installation-models/smart-decision/7.3.0
```

该命令会列出模型支持的场景字段、允许值和安装主路线。先查看这些字段，再根据实际局点填写场景，可以减少自然语言带来的歧义。

### 第四步：校验安装模型和文档来源

```powershell
uv run chm-agent validate-model installation-models/smart-decision/7.3.0 `
  --knowledge-base smart-decision-7.3.0-agent-docs
```

该命令检查模型结构、路线、步骤、约束以及引用的 Markdown 文件是否存在。模型校验失败时，不应继续生成现场可执行方案。

### 第五步：编译指定场景的安装流程

可以使用多个 `--set` 明确局点条件。例如，编译物理机全新安装流程：

```powershell
uv run chm-agent plan installation-models/smart-decision/7.3.0 `
  --set installation_nature=new `
  --set deployment_carrier=physical `
  --set topology=standard `
  --set hardware_provider=huawei `
  --set os_family=euleros `
  --set cpu_architecture=x86_64 `
  --set data_platform=external_fi `
  --set data_platform_access=admin `
  --set database=built_in `
  --set network_mode=multi_plane `
  --set ip_stack=ipv4 `
  --set optional_modules=none `
  -o physical-new-install.md
```

也可以把场景保存为 JSON 文件：

```json
{
  "installation_nature": "new",
  "deployment_carrier": "virtual",
  "topology": "standard",
  "data_platform": "external_fi",
  "data_platform_access": "non_om",
  "database": "mysql",
  "database_ssl": "enabled"
}
```

然后执行：

```powershell
uv run chm-agent plan installation-models/smart-decision/7.3.0 `
  --profile site-profile.json `
  -o virtual-new-install.md
```

编译结果有三种状态：

- `ready`：场景信息充分，已生成确定的安装路线；
- `needs_input`：仍有会影响步骤的阻断信息，结果中会列出待补充项和条件步骤；
- `invalid`：场景违反产品约束，不生成可执行的安装流程。

如需供其他程序处理，可以添加 `--format json` 输出结构化结果。

### 第六步：使用场景化安装技能

在能够加载本项目技能的 Agent 环境中，可以直接调用：

```text
使用 $plan-product-installation 为 Smart Decision 7.3.0 生成虚拟机全新安装方案。

局点条件：外置 FI、非 OM 用户、MySQL、启用客户端 SSL，不安装可选模块。
知识库：smart-decision-7.3.0-agent-docs
```

该技能会执行以下流程：

1. 确认产品版本、模型和知识库是否匹配；
2. 使用场景编译器选择主路线并检查组合；
3. 只读取已选步骤对应的 Markdown 证据；
4. 输出端到端步骤、条件分支、安装前检查、安装后验证、风险和待确认项；
5. 为关键要求、命令、参数和限制引用文档来源。

## 直接使用 Python

项目运行逻辑只依赖 Python 标准库。未使用 `uv` 时，也可以直接执行：

```powershell
py main.py "D:\docs\product.chm" -o product-agent-docs
```

安装模型命令建议通过项目命令 `chm-agent` 调用。

## 如何扩展到新的产品版本

1. 使用本工具把新版本 CHM 转换为独立知识库；
2. 从安装指南中识别会改变路线的场景字段和允许值；
3. 将主流程拆成可复用的原子步骤，并为每个步骤记录适用条件和 Markdown 来源；
4. 编写互斥组合、必填条件和产品限制；
5. 在 `installation-models/<产品>/<版本>/` 新建版本化模型；
6. 运行 `validate-model`，并为代表性组合补充自动化测试；
7. 由熟悉交付的人员评审后，再用于现场安装。

模型负责稳定地选择路线，原始 Markdown 负责提供操作证据，两者都应随产品版本一起维护，不能用旧版本模型解释新版本文档。
