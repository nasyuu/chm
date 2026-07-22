from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class ModelError(RuntimeError):
    pass


@dataclass
class InstallationModel:
    root: Path
    metadata: dict[str, Any]
    lock: dict[str, Any]
    constraints: list[dict[str, Any]]
    steps: dict[str, dict[str, Any]]
    routes: list[dict[str, Any]]

    @property
    def axes(self) -> dict[str, dict[str, Any]]:
        return self.metadata.get("axes", {})


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelError(f"缺少模型文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ModelError(f"JSON 格式错误 {path}:{exc.lineno}:{exc.colno}：{exc.msg}") from exc


def load_model(root: Path) -> InstallationModel:
    root = root.expanduser().resolve()
    metadata = _read_json(root / "model.json")
    lock = _read_json(root / "model.lock.json")
    constraints = _read_json(root / "constraints.json")
    routes = _read_json(root / "routes.json")
    steps: dict[str, dict[str, Any]] = {}
    steps_path = root / "steps.jsonl"
    try:
        lines = steps_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ModelError(f"缺少模型文件：{steps_path}") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            step = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ModelError(f"JSON 格式错误 {steps_path}:{line_number}：{exc.msg}") from exc
        step_id = step.get("id")
        if not isinstance(step_id, str) or not step_id:
            raise ModelError(f"{steps_path}:{line_number} 缺少步骤 id")
        if step_id in steps:
            raise ModelError(f"步骤 id 重复：{step_id}")
        steps[step_id] = step
    return InstallationModel(root, metadata, lock, constraints, steps, routes)


def _axis_values(axis: dict[str, Any]) -> set[str]:
    values = axis.get("values", {})
    return set(values if isinstance(values, list) else values.keys())


def _condition_state(profile: dict[str, Any], conditions: dict[str, Any]) -> bool | None:
    """Return True, False, or None when a required profile value is unknown."""
    unknown = False
    for field, expected in conditions.items():
        if field not in profile or profile[field] in (None, "", []):
            unknown = True
            continue
        actual = profile[field]
        accepted = expected if isinstance(expected, list) else [expected]
        if isinstance(actual, list):
            if not any(item in actual for item in accepted):
                return False
        elif actual not in accepted:
            return False
    return None if unknown else True


def _format_condition(conditions: dict[str, Any], axes: dict[str, dict[str, Any]]) -> str:
    parts = []
    for field, expected in conditions.items():
        axis = axes.get(field, {})
        label = axis.get("label", field)
        values = axis.get("values", {})
        expected_values = expected if isinstance(expected, list) else [expected]
        rendered = [values.get(value, value) if isinstance(values, dict) else value for value in expected_values]
        parts.append(f"{label}={'/'.join(rendered)}")
    return "，".join(parts) or "始终适用"


def _topological_steps(
    step_ids: Iterable[str],
    steps: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered_ids = list(dict.fromkeys(step_ids))
    selected = set(ordered_ids)
    positions = {step_id: index for index, step_id in enumerate(ordered_ids)}
    indegree = {step_id: 0 for step_id in ordered_ids}
    outgoing = {step_id: [] for step_id in ordered_ids}
    for step_id in ordered_ids:
        for dependency in steps[step_id].get("depends_on", []):
            if dependency not in selected:
                continue
            indegree[step_id] += 1
            outgoing[dependency].append(step_id)
    ready = sorted((item for item, degree in indegree.items() if degree == 0), key=positions.get)
    result: list[dict[str, Any]] = []
    while ready:
        step_id = ready.pop(0)
        result.append(steps[step_id])
        for target in outgoing[step_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort(key=positions.get)
    if len(result) != len(ordered_ids):
        raise ModelError("安装步骤依赖存在循环")
    return result


def validate_model(model: InstallationModel, knowledge_base: Path | None = None) -> list[str]:
    errors: list[str] = []
    if model.metadata.get("schema_version") != 1:
        errors.append("model.json 的 schema_version 必须为 1")
    if not model.metadata.get("product") or not model.metadata.get("version"):
        errors.append("model.json 必须包含 product 和 version")
    if model.lock.get("product") != model.metadata.get("product") or model.lock.get("version") != model.metadata.get("version"):
        errors.append("model.lock.json 的产品或版本与 model.json 不一致")
    source_hash = model.lock.get("source_chm", {}).get("sha256", "")
    if len(source_hash) != 64:
        errors.append("model.lock.json 必须记录有效的 CHM SHA-256")
    axes = model.axes
    if not isinstance(axes, dict) or not axes:
        errors.append("model.json 必须定义 axes")

    route_ids: set[str] = set()
    referenced_steps: set[str] = set()
    for route in model.routes:
        route_id = route.get("id")
        if not route_id or route_id in route_ids:
            errors.append(f"路线 id 缺失或重复：{route_id}")
        route_ids.add(route_id)
        for field, expected in route.get("when", {}).items():
            if field not in axes:
                errors.append(f"路线 {route_id} 引用了未知场景轴：{field}")
                continue
            accepted = expected if isinstance(expected, list) else [expected]
            unknown = set(accepted) - _axis_values(axes[field])
            if unknown:
                errors.append(f"路线 {route_id} 的 {field} 存在未知值：{sorted(unknown)}")
        for step_id in route.get("steps", []):
            referenced_steps.add(step_id)
            if step_id not in model.steps:
                errors.append(f"路线 {route_id} 引用了未知步骤：{step_id}")

    for step_id, step in model.steps.items():
        for field in step.get("applies_when", {}):
            if field not in axes:
                errors.append(f"步骤 {step_id} 引用了未知场景轴：{field}")
        for dependency in step.get("depends_on", []):
            if dependency not in model.steps:
                errors.append(f"步骤 {step_id} 依赖未知步骤：{dependency}")
        if not step.get("sources"):
            errors.append(f"步骤 {step_id} 没有文档来源")

    for constraint in model.constraints:
        constraint_id = constraint.get("id", "<unknown>")
        for section in ("when", "require", "forbid"):
            for field, expected in constraint.get(section, {}).items():
                if field not in axes:
                    errors.append(f"约束 {constraint_id} 引用了未知场景轴：{field}")
                    continue
                accepted = expected if isinstance(expected, list) else [expected]
                unknown = set(accepted) - _axis_values(axes[field])
                if unknown:
                    errors.append(f"约束 {constraint_id} 的 {field} 存在未知值：{sorted(unknown)}")
        if not constraint.get("sources"):
            errors.append(f"约束 {constraint_id} 没有文档来源")

    orphaned = set(model.steps) - referenced_steps
    if orphaned:
        errors.append(f"存在未被路线使用的步骤：{sorted(orphaned)}")

    if not errors:
        try:
            _topological_steps(model.steps, model.steps)
        except ModelError as exc:
            errors.append(str(exc))

    if knowledge_base:
        knowledge_base = knowledge_base.expanduser().resolve()
        for owner_id, item in list(model.steps.items()) + [
            (constraint.get("id", "<unknown>"), constraint) for constraint in model.constraints
        ]:
            for source in item.get("sources", []):
                source_file = source.get("file")
                if source_file and not (knowledge_base / source_file).is_file():
                    errors.append(f"{owner_id} 的来源不存在：{source_file}")
    return errors


def _validate_profile(model: InstallationModel, profile: dict[str, Any]) -> list[str]:
    errors = []
    for field, actual in profile.items():
        axis = model.axes.get(field)
        if not axis:
            errors.append(f"未知场景字段：{field}")
            continue
        actual_values = actual if isinstance(actual, list) else [actual]
        invalid = set(actual_values) - _axis_values(axis)
        if invalid:
            errors.append(f"{axis.get('label', field)}存在未知值：{sorted(invalid)}")
    return errors


def _constraint_results(
    model: InstallationModel,
    profile: dict[str, Any],
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    blockers: list[str] = []
    violations: list[str] = []
    applied: list[dict[str, Any]] = []
    for constraint in model.constraints:
        if _condition_state(profile, constraint.get("when", {})) is not True:
            continue
        applied.append(constraint)
        for field, expected in constraint.get("require", {}).items():
            if field not in profile or profile[field] in (None, "", []):
                blockers.append(f"{constraint['message']}；需确认 {model.axes[field].get('label', field)}")
            elif _condition_state(profile, {field: expected}) is False:
                violations.append(constraint["message"])
        for field, forbidden in constraint.get("forbid", {}).items():
            if field in profile and _condition_state(profile, {field: forbidden}) is True:
                violations.append(constraint["message"])
    return blockers, violations, applied


def compile_plan(model: InstallationModel, profile: dict[str, Any]) -> dict[str, Any]:
    profile_errors = _validate_profile(model, profile)
    blockers, violations, applied_constraints = _constraint_results(model, profile)
    violations.extend(profile_errors)

    compatible_routes = [
        route for route in model.routes
        if _condition_state(profile, route.get("when", {})) is not False
    ]
    exact_routes = [
        route for route in compatible_routes
        if _condition_state(profile, route.get("when", {})) is True
    ]
    route = exact_routes[0] if len(exact_routes) == 1 else None
    if len(exact_routes) > 1:
        violations.append(f"场景同时匹配多条安装路线：{[item['id'] for item in exact_routes]}")
    if not route and not violations:
        if not compatible_routes:
            violations.append("没有与当前条件兼容的安装路线")
        else:
            route_fields = set()
            for candidate in compatible_routes:
                route_fields.update(candidate.get("when", {}))
            missing = [field for field in route_fields if field not in profile]
            if missing:
                blockers.append(
                    "需要补充路线选择条件：" + "、".join(model.axes[field].get("label", field) for field in missing)
                )

    selected_steps: list[dict[str, Any]] = []
    if route:
        for field in route.get("required_fields", []):
            if field not in profile or profile[field] in (None, "", []):
                blockers.append(f"需确认 {model.axes[field].get('label', field)}")
        applicable_ids = []
        selected_step_map = dict(model.steps)
        for step_id in route.get("steps", []):
            step = model.steps[step_id]
            state = _condition_state(profile, step.get("applies_when", {}))
            if state is not False:
                item = dict(step)
                item["applicability"] = "适用" if state is True else "条件化"
                item["condition_text"] = _format_condition(step.get("applies_when", {}), model.axes)
                applicable_ids.append(step_id)
                selected_step_map[step_id] = item
        selected_steps = _topological_steps(applicable_ids, selected_step_map)

    blockers = list(dict.fromkeys(blockers))
    violations = list(dict.fromkeys(violations))
    status = "invalid" if violations else "needs_input" if blockers or not route else "ready"
    return {
        "schema_version": 1,
        "product": model.metadata.get("product"),
        "version": model.metadata.get("version"),
        "status": status,
        "profile": profile,
        "route": route,
        "candidate_routes": compatible_routes if not route else [],
        "blockers": blockers,
        "violations": violations,
        "constraints": applied_constraints,
        "steps": selected_steps,
    }


def render_plan_markdown(plan: dict[str, Any]) -> str:
    route = plan.get("route")
    lines = [
        f"# {plan['product']} {plan['version']} 安装执行手册",
        "",
        f"- 状态：`{plan['status']}`",
        f"- 路线：{route['title'] if route else '待确定'}",
        "",
        "## 场景档案",
        "",
    ]
    if plan["profile"]:
        lines.extend(f"- `{key}`：{value}" for key, value in plan["profile"].items())
    else:
        lines.append("- 尚未提供场景字段")

    if plan["violations"]:
        lines.extend(["", "## 不支持或冲突", ""])
        lines.extend(f"- {item}" for item in plan["violations"])
    if plan["blockers"]:
        lines.extend(["", "## 阻断项", ""])
        lines.extend(f"- [ ] {item}" for item in plan["blockers"])
    if plan["candidate_routes"]:
        lines.extend(["", "## 候选路线", ""])
        lines.extend(f"- `{item['id']}`：{item['title']}" for item in plan["candidate_routes"])
    if plan["constraints"]:
        lines.extend(["", "## 命中的组合约束", ""])
        for constraint in plan["constraints"]:
            sources = "、".join(f"`{item['file']}`" for item in constraint.get("sources", []))
            lines.append(f"- `{constraint['id']}`：{constraint['message']}（来源：{sources}）")

    if plan["steps"]:
        lines.extend([
            "",
            "## 端到端安装阶段",
            "",
            "| ID | 阶段 | 操作 | 适用性 | 预期结果 | 风险 | 来源 |",
            "|---|---|---|---|---|---|---|",
        ])
        for step in plan["steps"]:
            sources = "<br>".join(f"`{item['file']}`" for item in step.get("sources", []))
            applicability = step.get("applicability", "适用")
            if applicability == "条件化":
                applicability += f"：{step.get('condition_text', '')}"
            cells = [
                step["id"], step.get("phase", ""), step.get("action", step.get("title", "")),
                applicability, step.get("expected_result", ""), step.get("risk", "建议"), sources,
            ]
            lines.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in cells) + " |")

        lines.extend(["", "## 文档细节读取要求", ""])
        lines.append("执行前逐一打开上表来源文件，补齐命令、参数、前提、警告和验证细节；模型只负责选择正确分支。")
    return "\n".join(lines) + "\n"
