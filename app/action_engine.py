from __future__ import annotations

import asyncio
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.context_builder import ContextBuilder
from app.contracts import (
    ContextPacket,
    ActionExecuteRequest,
    ActionExecutionOptions,
    ActionExecutionReport,
    ActionPatchOperation,
    ActionPlan,
    ActionPlanRequest,
    ActionRisk,
    ActionRollbackReport,
    ActionRollbackRequest,
    ActionStep,
    ActionStepResult,
    ActionStepStatus,
    ActionType,
    ActionValidationIssue,
    ActionValidationReport,
    MemoryEntry,
    MemoryScope,
    ModelTier,
    ProviderResponse,
    RequestEnvelope,
    RetrievalResult,
    RouteDecision,
    ValidationSeverity,
)
from app.memory.repository import MemoryRepository
from app.workspace import split_scoped_project_id

if TYPE_CHECKING:
    from app.router import AIRouter


FILE_PATH_PATTERN = re.compile(r"([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]{1,10})")

CREATE_FILE_HINTS = {
    "create file",
    "new file",
    "cria arquivo",
    "novo arquivo",
    "add file",
}
PATCH_HINTS = {
    "patch",
    "diff",
    "replace",
    "altera",
    "modifica",
    "update",
}
DELETE_HINTS = {
    "delete",
    "remove",
    "apaga",
    "excluir",
}

HIGH_RISK_FILES = {
    "app/main.py",
    "app/settings.py",
    "requirements.txt",
    "package.json",
    "vite.config.ts",
}

LOW_RISK_EXTENSIONS = {
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
}


class ActionPlanner:
    def plan(self, *, request: ActionPlanRequest, retrieval: RetrievalResult) -> ActionPlan:
        prompt = request.prompt.strip()
        action_type = self._infer_action_type(prompt)
        explicit_targets = self._extract_explicit_targets(prompt)
        retrieval_targets = self._extract_retrieval_targets(retrieval)

        ordered_targets: list[str] = []
        seen: set[str] = set()
        for item in explicit_targets + retrieval_targets:
            normalized = self._normalize_relative_path(item)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered_targets.append(normalized)

        targets = self._prioritize_targets_for_prompt(ordered_targets, prompt)[: request.max_actions]
        warnings: list[str] = []

        if not targets:
            warnings.append("No target file was identified from prompt or retrieval context.")

        actions: list[ActionStep] = []
        for target in targets:
            risk = self._infer_risk(action_type=action_type, target=target)
            action = ActionStep(
                type=action_type,
                target=target,
                intent=prompt[:500],
                risk=risk,
                rationale="heuristic planner based on explicit targets + hot retrieval context",
            )
            self._attach_prompt_specific_mutations(action=action, prompt=prompt)
            actions.append(action)

        summary = (
            f"Generated {len(actions)} action(s) from prompt with mode {action_type.value}."
            if actions
            else "Planner could not infer target files."
        )

        assembled = retrieval.assembled or {}
        retrieval_payload = {
            "user_intent": assembled.get("user_intent", "general-query"),
            "relevant_systems": assembled.get("relevant_systems", []),
            "dependencies": assembled.get("dependencies", []),
            "risks": assembled.get("risks", []),
            "context_packet": assembled.get("context_packet", []),
        }

        return ActionPlan(
            plan_id=request.plan_id,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            user_id=request.user_id,
            prompt=request.prompt,
            summary=summary,
            actions=actions,
            warnings=warnings,
            retrieval=retrieval_payload,
        )

    def _infer_action_type(self, prompt: str) -> ActionType:
        lower = prompt.lower()
        if any(term in lower for term in DELETE_HINTS):
            return ActionType.DELETE_FILE
        if any(term in lower for term in PATCH_HINTS):
            return ActionType.PATCH_FILE
        if any(term in lower for term in CREATE_FILE_HINTS):
            return ActionType.CREATE_FILE
        if ("file" in lower or "arquivo" in lower) and any(term in lower for term in {"create", "new", "cria", "novo"}):
            return ActionType.CREATE_FILE
        return ActionType.UPDATE_FILE

    def _infer_risk(self, *, action_type: ActionType, target: str) -> ActionRisk:
        normalized = target.replace("\\", "/").strip("/").lower()
        suffix = Path(normalized).suffix.lower()

        if action_type == ActionType.DELETE_FILE:
            return ActionRisk.CRITICAL
        if normalized in HIGH_RISK_FILES:
            return ActionRisk.HIGH
        if normalized.startswith("app/") and normalized.endswith(".py"):
            return ActionRisk.HIGH
        if "/tests/" in f"/{normalized}/":
            return ActionRisk.LOW
        if suffix in LOW_RISK_EXTENSIONS:
            return ActionRisk.LOW
        return ActionRisk.MEDIUM

    def _extract_explicit_targets(self, prompt: str) -> list[str]:
        targets: list[str] = []
        for match in FILE_PATH_PATTERN.findall(prompt):
            normalized = self._normalize_relative_path(match)
            if normalized:
                targets.append(normalized)
        return targets

    def _extract_retrieval_targets(self, retrieval: RetrievalResult) -> list[str]:
        assembled = retrieval.assembled or {}
        context_packet = assembled.get("context_packet") or assembled.get("contexts") or []

        targets: list[str] = []
        for item in context_packet:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "")
            if source.startswith("artifact:file:"):
                targets.append(source.removeprefix("artifact:file:"))

        return targets

    def _normalize_relative_path(self, value: str) -> str:
        text = str(value or "").replace("\\", "/").strip()
        while text.startswith("./"):
            text = text[2:]
        return text.strip("/")

    def _prioritize_targets_for_prompt(self, targets: list[str], prompt: str) -> list[str]:
        if not self._is_ball_rate_prompt(prompt):
            return targets

        ranked = sorted(
            ((self._ball_rate_target_priority(target), target) for target in targets),
            key=lambda item: item[0],
            reverse=True,
        )
        if ranked and ranked[0][0] > 0:
            return [ranked[0][1]]

        preferred = [target for target in targets if self._is_likely_ball_rate_target(target)]
        if preferred:
            return [preferred[0]]
        return targets

    def _attach_prompt_specific_mutations(self, *, action: ActionStep, prompt: str) -> None:
        if action.type in {ActionType.CREATE_FILE, ActionType.DELETE_FILE}:
            return

        rate_value = self._extract_rate_value(prompt)
        if rate_value is None:
            return

        if not self._is_ball_rate_prompt(prompt):
            return

        if not self._is_likely_ball_rate_target(action.target):
            return

        if self._is_catch_formula_target(action.target):
            if self._is_increment_prompt(prompt):
                action.type = ActionType.PATCH_FILE
                action.patches = [
                    ActionPatchOperation(
                        find=(
                            r"(?im)^(\s*local\s+chance\s*=\s*chanceBase\s*\*\s*balls\[ballKey\]\.chanceMultiplier\s*)$"
                        ),
                        replace=rf"\g<1>\n    chance = chance + {rate_value}",
                        use_regex=True,
                    ),
                    ActionPatchOperation(
                        find=(
                            r"(?im)^(\s*local\s+chance\s*=\s*chanceBase\s*\*\s*[A-Za-z_][A-Za-z0-9_\.\[\]]*\s*)$"
                        ),
                        replace=rf"\g<1>\n    chance = chance + {rate_value}",
                        use_regex=True,
                    ),
                ]
                action.rationale = (
                    f"{action.rationale}; inferred catch chance additive patch (+{rate_value}) from intent"
                )
                return

        action.type = ActionType.PATCH_FILE
        action.patches = [
            ActionPatchOperation(
                find=(
                    r"(?im)"
                    r"((?:[A-Za-z_][A-Za-z0-9_\.]*\s*\[\s*['\"]?[A-Za-z_]*balls?[A-Za-z_]*rate[A-Za-z_]*['\"]?\s*\]"
                    r"|\[\s*['\"]?[A-Za-z_]*balls?[A-Za-z_]*rate[A-Za-z_]*['\"]?\s*\]"
                    r"|\b[A-Za-z_]*balls?[A-Za-z_]*rate[A-Za-z_]*\b)\s*(?:=|:)\s*)"
                    r"(\d+(?:\.\d+)?)"
                ),
                replace=rf"\g<1>{rate_value}",
                use_regex=True,
            ),
            ActionPatchOperation(
                find=(
                    r"(?im)"
                    r"((?:\b[A-Za-z_]*rate[A-Za-z_]*\b\s*\[\s*['\"][^'\"]*balls?[^'\"]*['\"]\s*\])\s*=\s*)"
                    r"(\d+(?:\.\d+)?)"
                ),
                replace=rf"\g<1>{rate_value}",
                use_regex=True,
            ),
            ActionPatchOperation(
                find=(
                    r"(?im)"
                    r"((?:\b[A-Za-z_]*balls?[A-Za-z_]*\b\s*\[\s*['\"][^'\"]*rate[^'\"]*['\"]\s*\])\s*=\s*)"
                    r"(\d+(?:\.\d+)?)"
                ),
                replace=rf"\g<1>{rate_value}",
                use_regex=True,
            ),
            ActionPatchOperation(
                find=r"(?im)^(\s*[^\n#]*ball[^\n#]*rate[^\n#]*[=:]\s*)(\d+(?:\.\d+)?)(\s*,?\s*)$",
                replace=rf"\g<1>{rate_value}\g<3>",
                use_regex=True,
            ),
        ]
        action.rationale = (
            f"{action.rationale}; inferred balls-rate parameter patch from intent"
        )

    def _extract_rate_value(self, prompt: str) -> str | None:
        lower = prompt.lower()

        explicit = re.search(
            r"(?:rate|taxa|parametro|par[âa]metro)\D{0,20}(?:para|to|=)\s*(\d+(?:\.\d+)?)",
            lower,
            flags=re.IGNORECASE,
        )
        if explicit:
            return explicit.group(1)

        generic_to = re.search(r"(?:para|to|=)\s*(\d+(?:\.\d+)?)", lower, flags=re.IGNORECASE)
        if generic_to:
            return generic_to.group(1)

        numbers = re.findall(r"\d+(?:\.\d+)?", lower)
        if numbers:
            return numbers[-1]
        return None

    def _is_ball_rate_prompt(self, prompt: str) -> bool:
        lower = prompt.lower()
        has_ball = any(term in lower for term in {"ball", "balls", "pokeball", "pokeballs"})
        has_rate = any(term in lower for term in {"rate", "taxa"})
        return has_ball and has_rate

    def _is_likely_ball_rate_target(self, target: str) -> bool:
        lower = target.replace("\\", "/").lower()
        if not lower.endswith((".lua", ".py", ".json", ".yml", ".yaml", ".toml", ".ini")):
            return False
        if self._is_catch_formula_target(lower):
            return True
        if "newfunction" in lower:
            return True
        if "ball" in lower:
            return True
        return False

    def _ball_rate_target_priority(self, target: str) -> int:
        lower = target.replace("\\", "/").lower()
        if not lower.endswith((".lua", ".py", ".json", ".yml", ".yaml", ".toml", ".ini")):
            return 0
        if self._is_catch_formula_target(lower):
            return 4
        if "newfunction" in lower:
            return 3
        if "ball" in lower:
            return 2
        return 0

    def _is_catch_formula_target(self, target: str) -> bool:
        lower = target.replace("\\", "/").lower()
        return lower.endswith("/catch.lua") or lower.endswith("catch.lua")

    def _is_increment_prompt(self, prompt: str) -> bool:
        lower = prompt.lower()
        plus_patterns = (
            r"\+\s*\d+(?:\.\d+)?",
            r"(?:aumenta|aumente|increase|add|somar|soma|incrementa|increment)\D{0,20}(?:em|by|\+)\s*\d+(?:\.\d+)?",
        )
        return any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in plus_patterns)


class ActionValidator:
    def validate(
        self,
        *,
        plan: ActionPlan,
        workspace_root: Path,
        blocked_path_prefixes: tuple[str, ...],
        allow_high_risk: bool,
        allow_delete: bool,
        strict_for_execution: bool,
        max_file_bytes: int,
    ) -> ActionValidationReport:
        issues: list[ActionValidationIssue] = []
        blocked_steps: set[str] = set()

        for step in plan.actions:
            normalized_target, target_path = self._resolve_target(workspace_root=workspace_root, target=step.target)
            if not normalized_target or target_path is None:
                issues.append(
                    ActionValidationIssue(
                        step_id=step.step_id,
                        severity=ValidationSeverity.ERROR,
                        code="invalid_target",
                        message="Target path is invalid, absolute, or escapes workspace root.",
                    )
                )
                blocked_steps.add(step.step_id)
                continue

            if self._is_blocked_target(normalized_target, blocked_path_prefixes):
                issues.append(
                    ActionValidationIssue(
                        step_id=step.step_id,
                        severity=ValidationSeverity.ERROR,
                        code="blocked_target",
                        message=f"Target path {normalized_target} is blocked by safety policy.",
                    )
                )
                blocked_steps.add(step.step_id)

            if step.type == ActionType.DELETE_FILE and not allow_delete:
                issues.append(
                    ActionValidationIssue(
                        step_id=step.step_id,
                        severity=ValidationSeverity.ERROR,
                        code="delete_not_allowed",
                        message="Delete action is disabled by runtime settings.",
                    )
                )
                blocked_steps.add(step.step_id)

            if step.risk in {ActionRisk.HIGH, ActionRisk.CRITICAL} and not allow_high_risk:
                issues.append(
                    ActionValidationIssue(
                        step_id=step.step_id,
                        severity=ValidationSeverity.ERROR,
                        code="high_risk_denied",
                        message="High risk action requires allow_high_risk=true.",
                    )
                )
                blocked_steps.add(step.step_id)

            if strict_for_execution:
                if step.type in {ActionType.UPDATE_FILE, ActionType.PATCH_FILE}:
                    if not target_path.exists():
                        issues.append(
                            ActionValidationIssue(
                                step_id=step.step_id,
                                severity=ValidationSeverity.ERROR,
                                code="target_missing",
                                message="Update/Patch target file does not exist.",
                            )
                        )
                        blocked_steps.add(step.step_id)
                    elif target_path.is_file() and target_path.stat().st_size > max_file_bytes:
                        issues.append(
                            ActionValidationIssue(
                                step_id=step.step_id,
                                severity=ValidationSeverity.ERROR,
                                code="file_too_large",
                                message=f"Target exceeds max_file_bytes={max_file_bytes}.",
                            )
                        )
                        blocked_steps.add(step.step_id)

                    if not step.patches and step.content is None:
                        issues.append(
                            ActionValidationIssue(
                                step_id=step.step_id,
                                severity=ValidationSeverity.ERROR,
                                code="missing_mutation",
                                message="Update/Patch action must include content or patches.",
                            )
                        )
                        blocked_steps.add(step.step_id)

                if step.type == ActionType.CREATE_FILE and step.content is None:
                    issues.append(
                        ActionValidationIssue(
                            step_id=step.step_id,
                            severity=ValidationSeverity.WARNING,
                            code="empty_create_content",
                            message="Create action has no content and will use generated placeholder.",
                        )
                    )

                if step.type == ActionType.DELETE_FILE and not target_path.exists():
                    issues.append(
                        ActionValidationIssue(
                            step_id=step.step_id,
                            severity=ValidationSeverity.WARNING,
                            code="delete_target_missing",
                            message="Delete target file does not exist.",
                        )
                    )

        has_error = any(item.severity == ValidationSeverity.ERROR for item in issues)
        return ActionValidationReport(
            ok=not has_error,
            issues=issues,
            blocked_steps=sorted(blocked_steps),
        )

    def _resolve_target(self, *, workspace_root: Path, target: str) -> tuple[str, Path | None]:
        raw = str(target or "").strip()
        if not raw:
            return "", None

        candidate = raw.replace("\\", "/").strip()
        if re.match(r"^[A-Za-z]:", candidate):
            return "", None
        if candidate.startswith("/"):
            return "", None

        while candidate.startswith("./"):
            candidate = candidate[2:]

        parts = [item for item in candidate.split("/") if item not in {"", "."}]
        if not parts or ".." in parts:
            return "", None

        normalized = "/".join(parts)
        target_path = (workspace_root / normalized).resolve()

        try:
            target_path.relative_to(workspace_root)
        except ValueError:
            return "", None

        return normalized, target_path

    def _is_blocked_target(self, target: str, blocked_path_prefixes: tuple[str, ...]) -> bool:
        lowered = target.strip("/").lower()
        for item in blocked_path_prefixes:
            prefix = item.strip("/").lower()
            if not prefix:
                continue
            if lowered == prefix or lowered.startswith(prefix + "/"):
                return True
        return False


class ActionExecutor:
    def __init__(
        self,
        *,
        workspace_root: Path,
        backup_root: Path,
        allow_delete: bool,
        max_file_bytes: int,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.backup_root = backup_root.resolve()
        self.allow_delete = allow_delete
        self.max_file_bytes = max_file_bytes
        self.validator = ActionValidator()

    def execute(
        self,
        *,
        plan: ActionPlan,
        options: ActionExecutionOptions,
        validation: ActionValidationReport,
    ) -> ActionExecutionReport:
        report = ActionExecutionReport(
            plan_id=plan.plan_id,
            dry_run=options.dry_run,
            validation=validation,
        )

        blocked = set(validation.blocked_steps)
        operations: list[dict[str, str]] = []
        execution_dir = self.backup_root / report.execution_id

        for step in plan.actions:
            if step.step_id in blocked:
                report.skipped += 1
                report.results.append(
                    ActionStepResult(
                        step_id=step.step_id,
                        target=step.target,
                        status=ActionStepStatus.SKIPPED,
                        message="Blocked by validation policy.",
                    )
                )
                continue

            if options.dry_run:
                report.skipped += 1
                report.results.append(
                    ActionStepResult(
                        step_id=step.step_id,
                        target=step.target,
                        status=ActionStepStatus.PLANNED,
                        message="Dry run only. No file changes were applied.",
                    )
                )
                continue

            try:
                step_result, operation = self._apply_step(step=step, execution_dir=execution_dir)
            except Exception as exc:
                report.failed += 1
                report.results.append(
                    ActionStepResult(
                        step_id=step.step_id,
                        target=step.target,
                        status=ActionStepStatus.FAILED,
                        message=f"Execution failed: {exc}",
                    )
                )
                if options.auto_rollback_on_error and report.applied > 0:
                    rollback = self.rollback(execution_id=report.execution_id)
                    report.rollback_performed = True
                    report.rollback_restored_files = rollback.restored_files + rollback.removed_files
                    report.applied = 0
                    report.changed_files = []
                    for item in report.results:
                        if item.status == ActionStepStatus.APPLIED:
                            item.status = ActionStepStatus.ROLLED_BACK
                            item.message = "Rolled back due to execution failure in the plan."
                break

            report.results.append(step_result)
            if step_result.status == ActionStepStatus.APPLIED:
                report.applied += 1
                report.changed_files.append(step_result.target)
                if operation is not None:
                    operations.append(operation)
            elif step_result.status == ActionStepStatus.SKIPPED:
                report.skipped += 1
            else:
                report.failed += 1

        if not options.dry_run and operations:
            self._persist_manifest(execution_id=report.execution_id, operations=operations)

        return report

    def rollback(self, *, execution_id: str) -> ActionRollbackReport:
        manifest_path = self.backup_root / execution_id / "manifest.json"
        report = ActionRollbackReport(execution_id=execution_id)

        if not manifest_path.exists():
            report.notes.append("Manifest not found for execution id.")
            return report

        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        operations = payload.get("operations", [])
        workspace_root_value = str(payload.get("workspace_root") or "").strip()
        workspace_root = Path(workspace_root_value).resolve() if workspace_root_value else self.workspace_root

        for item in reversed(operations):
            op_type = str(item.get("op") or "")
            target = str(item.get("target") or "")
            backup = str(item.get("backup") or "")

            target_path = (workspace_root / target).resolve()

            if op_type == "create":
                if target_path.exists():
                    target_path.unlink()
                    report.removed_files += 1
                else:
                    report.skipped_files += 1
                continue

            backup_path = (self.backup_root / execution_id / backup).resolve()
            if not backup_path.exists():
                report.skipped_files += 1
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, target_path)
            report.restored_files += 1

        if report.restored_files == 0 and report.removed_files == 0 and report.skipped_files == 0:
            report.notes.append("No operations found in manifest.")

        return report

    def _apply_step(self, *, step: ActionStep, execution_dir: Path) -> tuple[ActionStepResult, dict[str, str] | None]:
        normalized_target, target_path = self.validator._resolve_target(workspace_root=self.workspace_root, target=step.target)
        if not normalized_target or target_path is None:
            return (
                ActionStepResult(
                    step_id=step.step_id,
                    target=step.target,
                    status=ActionStepStatus.FAILED,
                    message="Target path could not be resolved.",
                ),
                None,
            )

        if step.type == ActionType.CREATE_FILE:
            if target_path.exists():
                return (
                    ActionStepResult(
                        step_id=step.step_id,
                        target=normalized_target,
                        status=ActionStepStatus.SKIPPED,
                        message="Target already exists.",
                    ),
                    None,
                )

            target_path.parent.mkdir(parents=True, exist_ok=True)
            content = step.content if step.content is not None else self._placeholder_content(step)
            self._write_text(target_path, content)
            return (
                ActionStepResult(
                    step_id=step.step_id,
                    target=normalized_target,
                    status=ActionStepStatus.APPLIED,
                    message="File created.",
                    bytes_written=len(content.encode("utf-8")),
                ),
                {
                    "op": "create",
                    "target": normalized_target,
                },
            )

        if step.type in {ActionType.UPDATE_FILE, ActionType.PATCH_FILE}:
            if not target_path.exists():
                return (
                    ActionStepResult(
                        step_id=step.step_id,
                        target=normalized_target,
                        status=ActionStepStatus.FAILED,
                        message="Target file does not exist.",
                    ),
                    None,
                )

            original = target_path.read_text(encoding="utf-8")
            updated = self._mutate_text(original=original, content=step.content, patches=step.patches)
            if updated is None:
                return (
                    ActionStepResult(
                        step_id=step.step_id,
                        target=normalized_target,
                        status=ActionStepStatus.FAILED,
                        message="No content or patches were provided.",
                    ),
                    None,
                )

            if updated == original:
                return (
                    ActionStepResult(
                        step_id=step.step_id,
                        target=normalized_target,
                        status=ActionStepStatus.SKIPPED,
                        message="Patch did not change file contents.",
                    ),
                    None,
                )

            backup_rel = self._backup_file(target_path=target_path, execution_dir=execution_dir)
            self._write_text(target_path, updated)
            return (
                ActionStepResult(
                    step_id=step.step_id,
                    target=normalized_target,
                    status=ActionStepStatus.APPLIED,
                    message="File updated.",
                    backup_path=backup_rel,
                    bytes_written=len(updated.encode("utf-8")),
                ),
                {
                    "op": "update",
                    "target": normalized_target,
                    "backup": backup_rel,
                },
            )

        if step.type == ActionType.DELETE_FILE:
            if not self.allow_delete:
                return (
                    ActionStepResult(
                        step_id=step.step_id,
                        target=normalized_target,
                        status=ActionStepStatus.FAILED,
                        message="Delete is disabled by settings.",
                    ),
                    None,
                )

            if not target_path.exists():
                return (
                    ActionStepResult(
                        step_id=step.step_id,
                        target=normalized_target,
                        status=ActionStepStatus.SKIPPED,
                        message="File already missing.",
                    ),
                    None,
                )

            backup_rel = self._backup_file(target_path=target_path, execution_dir=execution_dir)
            target_path.unlink()
            return (
                ActionStepResult(
                    step_id=step.step_id,
                    target=normalized_target,
                    status=ActionStepStatus.APPLIED,
                    message="File deleted.",
                    backup_path=backup_rel,
                ),
                {
                    "op": "delete",
                    "target": normalized_target,
                    "backup": backup_rel,
                },
            )

        return (
            ActionStepResult(
                step_id=step.step_id,
                target=normalized_target,
                status=ActionStepStatus.FAILED,
                message=f"Unsupported action type {step.type.value}.",
            ),
            None,
        )

    def _mutate_text(
        self,
        *,
        original: str,
        content: str | None,
        patches: list[ActionPatchOperation],
    ) -> str | None:
        if content is not None:
            return content

        if not patches:
            return None

        updated = original
        matched_any = False
        for patch in patches:
            if patch.use_regex:
                count = 0 if patch.replace_all else 1
                candidate, changed = re.subn(patch.find, patch.replace, updated, count=count)
                if changed > 0:
                    updated = candidate
                    matched_any = True
                continue

            if patch.find not in updated:
                continue
            if patch.replace_all:
                updated = updated.replace(patch.find, patch.replace)
            else:
                updated = updated.replace(patch.find, patch.replace, 1)
            matched_any = True

        if not matched_any:
            raise ValueError("Patch patterns did not match file contents.")

        return updated

    def _backup_file(self, *, target_path: Path, execution_dir: Path) -> str:
        relative_target = target_path.relative_to(self.workspace_root).as_posix()
        backup_rel = Path("backups") / relative_target
        backup_path = execution_dir / backup_rel
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_path, backup_path)
        return backup_rel.as_posix()

    def _write_text(self, target_path: Path, content: str) -> None:
        encoded = content.encode("utf-8")
        if len(encoded) > self.max_file_bytes:
            raise ValueError(f"content exceeds max_file_bytes={self.max_file_bytes}")
        target_path.write_text(content, encoding="utf-8")

    def _persist_manifest(self, *, execution_id: str, operations: list[dict[str, str]]) -> None:
        execution_dir = self.backup_root / execution_id
        execution_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "execution_id": execution_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "workspace_root": self.workspace_root.as_posix(),
            "operations": operations,
        }
        (execution_dir / "manifest.json").write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    def _placeholder_content(self, step: ActionStep) -> str:
        return (
            "# Auto-generated by BRASA Action Engine\n"
            f"# Intent: {step.intent[:200]}\n"
        )


class CognitiveActionEngine:
    def __init__(
        self,
        *,
        context_builder: ContextBuilder,
        memory_repository: MemoryRepository,
        workspace_root: Path,
        backup_root: Path,
        blocked_path_prefixes: tuple[str, ...],
        allow_delete: bool,
        max_file_bytes: int,
        router: AIRouter | None = None,
        model_assist_enabled: bool = True,
        model_assist_tier: str = "flash",
    ) -> None:
        self.context_builder = context_builder
        self.memory_repository = memory_repository
        self.workspace_root = workspace_root.resolve()
        self.backup_root = backup_root.resolve()
        self.blocked_path_prefixes = tuple(item.strip().replace("\\", "/") for item in blocked_path_prefixes if item)
        self.allow_delete = allow_delete
        self.max_file_bytes = max_file_bytes
        self.router = router
        self.model_assist_enabled = model_assist_enabled
        self.model_assist_tier = self._resolve_model_assist_tier(model_assist_tier)

        self.planner = ActionPlanner()
        self.validator = ActionValidator()
        self.executor = ActionExecutor(
            workspace_root=self.workspace_root,
            backup_root=self.backup_root,
            allow_delete=self.allow_delete,
            max_file_bytes=self.max_file_bytes,
        )

    def plan(self, request: ActionPlanRequest) -> tuple[ActionPlan, RetrievalResult]:
        envelope = RequestEnvelope(
            request_id=request.plan_id,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            user_id=request.user_id,
            prompt=request.prompt,
            metadata={
                **request.metadata,
                "task_type": "action_planning",
                "action_engine_version": "v1",
            },
        )
        context_packet, retrieval = self.context_builder.build(envelope)
        heuristic_plan = self.planner.plan(request=request, retrieval=retrieval)

        assisted_plan = self._model_assisted_plan(
            request=request,
            retrieval=retrieval,
            context_packet=context_packet,
            heuristic_plan=heuristic_plan,
        )
        if assisted_plan is not None:
            return assisted_plan, retrieval

        return heuristic_plan, retrieval

    def execute(self, request: ActionExecuteRequest) -> ActionExecutionReport:
        execution_workspace_root = self._resolve_execution_workspace_root(request=request)

        validation = self.validator.validate(
            plan=request.plan,
            workspace_root=execution_workspace_root,
            blocked_path_prefixes=self.blocked_path_prefixes,
            allow_high_risk=request.options.allow_high_risk,
            allow_delete=self.allow_delete,
            strict_for_execution=not request.options.dry_run,
            max_file_bytes=self.max_file_bytes,
        )

        executor = ActionExecutor(
            workspace_root=execution_workspace_root,
            backup_root=self.backup_root,
            allow_delete=self.allow_delete,
            max_file_bytes=self.max_file_bytes,
        )

        report = executor.execute(
            plan=request.plan,
            options=request.options,
            validation=validation,
        )

        if not request.options.dry_run and report.applied > 0:
            self.memory_repository.add_entry(
                MemoryEntry(
                    project_id=request.project_id,
                    user_id=request.user_id,
                    scope=MemoryScope.EPISODIC,
                    content=(
                        f"ActionPlan: {request.plan.plan_id}\n"
                        f"AppliedFiles: {', '.join(report.changed_files[:20])}\n"
                        f"Prompt: {request.plan.prompt[:600]}"
                    ),
                    tags=["action", "execution", "auto"],
                    confidence=0.78,
                    provenance={
                        "execution_id": report.execution_id,
                        "applied": report.applied,
                        "failed": report.failed,
                    },
                )
            )

        return report

    def rollback(self, request: ActionRollbackRequest) -> ActionRollbackReport:
        return self.executor.rollback(execution_id=request.execution_id)

    def _model_assisted_plan(
        self,
        *,
        request: ActionPlanRequest,
        retrieval: RetrievalResult,
        context_packet: ContextPacket,
        heuristic_plan: ActionPlan,
    ) -> ActionPlan | None:
        if not self.model_assist_enabled or self.router is None:
            return None

        prompt = self._build_model_assist_prompt(
            request=request,
            retrieval=retrieval,
            heuristic_plan=heuristic_plan,
        )
        envelope = RequestEnvelope(
            request_id=f"{request.plan_id}-model-assist",
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            user_id=request.user_id,
            prompt=prompt,
            tier_hint=self.model_assist_tier,
            metadata={
                **request.metadata,
                "task_type": "action_planning",
                "action_engine_version": "v1-model-assist",
                "require_alibaba_final_response": True,
                "retrieval": retrieval.assembled,
            },
        )

        try:
            response, decision = self._run_router_generate_sync(
                envelope=envelope,
                context=context_packet,
            )
        except Exception:
            return None

        payload = self._extract_json_payload(response.answer)
        if payload is None:
            return None

        actions = self._deserialize_model_actions(
            payload=payload,
            fallback_prompt=request.prompt,
            max_actions=request.max_actions,
        )
        if not actions:
            return None

        planning_workspace_root = self._resolve_execution_workspace_root(
            request=ActionExecuteRequest(
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                user_id=request.user_id,
                plan=heuristic_plan,
                options=ActionExecutionOptions(dry_run=True),
            )
        )
        actions, refinement_notes = self._refine_model_actions(
            actions=actions,
            fallback_prompt=request.prompt,
            workspace_root=planning_workspace_root,
        )

        warnings = list(heuristic_plan.warnings)
        raw_warnings = payload.get("warnings", [])
        if isinstance(raw_warnings, list):
            warnings.extend(str(item) for item in raw_warnings[:8])
        warnings.extend(refinement_notes[:8])

        warnings.append(
            f"model-assisted planning applied via {decision.provider}:{decision.model_name}"
        )

        summary = str(payload.get("summary") or "").strip() or heuristic_plan.summary

        return heuristic_plan.model_copy(
            update={
                "summary": summary,
                "actions": actions,
                "warnings": warnings,
            }
        )

    def _build_model_assist_prompt(
        self,
        *,
        request: ActionPlanRequest,
        retrieval: RetrievalResult,
        heuristic_plan: ActionPlan,
    ) -> str:
        assembled = retrieval.assembled or {}
        context_packet = assembled.get("context_packet") or assembled.get("contexts") or []

        candidate_sources: list[str] = []
        for item in context_packet:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip()
            if source.startswith("artifact:file:"):
                source = source.removeprefix("artifact:file:")
            if source and source not in candidate_sources:
                candidate_sources.append(source)

        heuristic_actions = [
            {
                "type": action.type.value,
                "target": action.target,
                "risk": action.risk.value,
                "intent": action.intent,
            }
            for action in heuristic_plan.actions[:6]
        ]

        return (
            "You are BRASA Action Planner.\n"
            "Return ONLY valid JSON (no markdown, no explanations) with this schema:\n"
            "{\n"
            '  "summary": "string",\n'
            '  "warnings": ["string"],\n'
            "  \"actions\": [\n"
            "    {\n"
            '      "type": "create_file|update_file|patch_file|delete_file",\n'
            '      "target": "relative/path.ext",\n'
            '      "intent": "string",\n'
            '      "risk": "low|medium|high|critical",\n'
            '      "rationale": "string",\n'
            '      "content": "string or null",\n'
            '      "patches": [\n'
            "        {\n"
            '          "find": "string",\n'
            '          "replace": "string",\n'
            '          "replace_all": false,\n'
            '          "use_regex": false\n'
            "        }\n"
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- Prefer candidate target files listed below.\n"
            "- For parameter tweaks, prefer patch_file with precise patches.\n"
            "- If unsure, keep a single safest action.\n"
            "- Never output absolute paths.\n\n"
            f"User request:\n{request.prompt}\n\n"
            f"Candidate files:\n{json.dumps(candidate_sources[:30], ensure_ascii=True, indent=2)}\n\n"
            f"Retrieved systems:\n{json.dumps(assembled.get('relevant_systems', [])[:20], ensure_ascii=True, indent=2)}\n\n"
            f"Retrieved dependencies:\n{json.dumps(assembled.get('dependencies', [])[:30], ensure_ascii=True, indent=2)}\n\n"
            f"Heuristic baseline:\n{json.dumps(heuristic_actions, ensure_ascii=True, indent=2)}"
        )

    def _run_router_generate_sync(
        self,
        *,
        envelope: RequestEnvelope,
        context: ContextPacket,
    ) -> tuple[ProviderResponse, RouteDecision]:
        if self.router is None:
            raise RuntimeError("router is not configured")

        coroutine = self.router.generate(envelope=envelope, context=context)
        try:
            return asyncio.run(coroutine)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coroutine)
            finally:
                loop.close()

    def _extract_json_payload(self, text: str) -> dict[str, Any] | None:
        raw = (text or "").strip()
        if not raw:
            return None

        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```$", "", raw).strip()

        parsed = self._try_parse_json(raw)
        if parsed is not None:
            return parsed

        first = raw.find("{")
        last = raw.rfind("}")
        if first >= 0 and last > first:
            return self._try_parse_json(raw[first : last + 1])

        return None

    def _try_parse_json(self, text: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(text)
        except Exception:
            return None
        if isinstance(payload, dict):
            return payload
        return None

    def _deserialize_model_actions(
        self,
        *,
        payload: dict[str, Any],
        fallback_prompt: str,
        max_actions: int,
    ) -> list[ActionStep]:
        raw_actions = payload.get("actions", [])
        if not isinstance(raw_actions, list):
            return []

        actions: list[ActionStep] = []
        for raw in raw_actions:
            if not isinstance(raw, dict):
                continue

            target = self.planner._normalize_relative_path(str(raw.get("target") or ""))
            intent = str(raw.get("intent") or fallback_prompt).strip()
            if not target or len(intent) < 2:
                continue

            action_type = self._safe_action_type(str(raw.get("type") or "update_file"))
            risk = self._safe_action_risk(str(raw.get("risk") or "medium"))

            patches: list[ActionPatchOperation] = []
            raw_patches = raw.get("patches", [])
            if isinstance(raw_patches, list):
                for item in raw_patches:
                    if not isinstance(item, dict):
                        continue
                    find = str(item.get("find") or "").strip()
                    if not find:
                        continue
                    patches.append(
                        ActionPatchOperation(
                            find=find,
                            replace=str(item.get("replace") or ""),
                            replace_all=bool(item.get("replace_all", False)),
                            use_regex=bool(item.get("use_regex", False)),
                        )
                    )

            content_raw = raw.get("content")
            content = None if content_raw is None else str(content_raw)
            rationale = str(raw.get("rationale") or "model-assisted planning")

            action = ActionStep(
                type=action_type,
                target=target,
                intent=intent[:500],
                risk=risk,
                rationale=rationale,
                patches=patches,
                content=content,
            )

            if action.type in {ActionType.UPDATE_FILE, ActionType.PATCH_FILE} and action.content is None and not action.patches:
                self.planner._attach_prompt_specific_mutations(action=action, prompt=fallback_prompt)

            actions.append(action)
            if len(actions) >= max_actions:
                break

        return actions

    def _refine_model_actions(
        self,
        *,
        actions: list[ActionStep],
        fallback_prompt: str,
        workspace_root: Path,
    ) -> tuple[list[ActionStep], list[str]]:
        refined: list[ActionStep] = []
        notes: list[str] = []

        for action in actions:
            candidate = action.model_copy(deep=True)

            if self.planner._is_ball_rate_prompt(fallback_prompt):
                retargeted = self._retarget_ball_rate_action_if_needed(
                    action=candidate,
                    workspace_root=workspace_root,
                )
                if retargeted:
                    notes.append(
                        f"retargeted action target to {candidate.target} based on workspace evidence"
                    )

            if candidate.type in {ActionType.UPDATE_FILE, ActionType.PATCH_FILE} and candidate.content is None:
                if not candidate.patches:
                    self.planner._attach_prompt_specific_mutations(
                        action=candidate,
                        prompt=fallback_prompt,
                    )

                if candidate.patches and not self._patches_match_target(
                    action=candidate,
                    workspace_root=workspace_root,
                ):
                    original_target = candidate.target
                    candidate.patches = []
                    self.planner._attach_prompt_specific_mutations(
                        action=candidate,
                        prompt=fallback_prompt,
                    )

                    if candidate.patches and self._patches_match_target(
                        action=candidate,
                        workspace_root=workspace_root,
                    ):
                        notes.append(
                            f"repaired patch operations using heuristic mutations for {candidate.target}"
                        )
                    else:
                        alternate = self._infer_alternate_ball_rate_target(
                            current_target=original_target,
                            workspace_root=workspace_root,
                        )
                        if alternate is not None:
                            candidate.target = alternate
                            candidate.patches = []
                            self.planner._attach_prompt_specific_mutations(
                                action=candidate,
                                prompt=fallback_prompt,
                            )
                            if candidate.patches and self._patches_match_target(
                                action=candidate,
                                workspace_root=workspace_root,
                            ):
                                notes.append(
                                    f"moved patch target from {original_target} to {candidate.target} for patch match"
                                )

            refined.append(candidate)

        return refined, notes

    def _retarget_ball_rate_action_if_needed(self, *, action: ActionStep, workspace_root: Path) -> bool:
        normalized_target, target_path = self.validator._resolve_target(
            workspace_root=workspace_root,
            target=action.target,
        )

        if target_path is not None and target_path.exists():
            return False

        alternate = self._infer_alternate_ball_rate_target(
            current_target=normalized_target or action.target,
            workspace_root=workspace_root,
        )
        if alternate is None:
            return False

        action.target = alternate
        return True

    def _infer_alternate_ball_rate_target(self, *, current_target: str, workspace_root: Path) -> str | None:
        normalized = current_target.replace("\\", "/").lower()
        candidates = [
            "data/actions/scripts/poke/catch.lua",
            "data/actions/scripts/poke/catch.lua",
            "data/lib/core/newfunctions.lua",
            "data/scripts/systems/pokemon/pokeballs.lua",
        ]

        for item in candidates:
            normalized_item, target_path = self.validator._resolve_target(
                workspace_root=workspace_root,
                target=item,
            )
            if not normalized_item or target_path is None:
                continue
            if target_path.exists() and target_path.is_file():
                if normalized.endswith("pokeballs.lua") and normalized_item.endswith("catch.lua"):
                    return normalized_item
                if not normalized.endswith(Path(normalized_item).name):
                    return normalized_item

        try:
            for file_path in workspace_root.rglob("catch.lua"):
                if not file_path.is_file():
                    continue
                relative = file_path.relative_to(workspace_root).as_posix()
                return relative
        except Exception:
            return None

        return None

    def _patches_match_target(self, *, action: ActionStep, workspace_root: Path) -> bool:
        if action.content is not None:
            return True

        normalized_target, target_path = self.validator._resolve_target(
            workspace_root=workspace_root,
            target=action.target,
        )
        if not normalized_target or target_path is None or not target_path.exists() or not target_path.is_file():
            return False

        try:
            content = target_path.read_text(encoding="utf-8")
        except Exception:
            return False

        for patch in action.patches:
            if patch.use_regex:
                try:
                    if re.search(patch.find, content) is not None:
                        return True
                except re.error:
                    continue
                continue

            if patch.find and patch.find in content:
                return True

        return False

    def _safe_action_type(self, value: str) -> ActionType:
        try:
            return ActionType(value.strip().lower())
        except Exception:
            return ActionType.UPDATE_FILE

    def _safe_action_risk(self, value: str) -> ActionRisk:
        try:
            return ActionRisk(value.strip().lower())
        except Exception:
            return ActionRisk.MEDIUM

    def _resolve_model_assist_tier(self, value: str) -> ModelTier:
        raw = (value or "").strip().lower()
        mapping = {
            "local": ModelTier.LOCAL,
            "flash": ModelTier.FLASH,
            "plus": ModelTier.PLUS,
            "max": ModelTier.MAX,
        }
        return mapping.get(raw, ModelTier.FLASH)

    def _resolve_execution_workspace_root(self, *, request: ActionExecuteRequest) -> Path:
        resolved = self._resolve_project_source_path(
            workspace_id=request.workspace_id,
            project_id=request.project_id,
        )
        if resolved is not None:
            return resolved

        resolved = self._resolve_project_source_path(
            workspace_id=request.plan.workspace_id,
            project_id=request.plan.project_id,
        )
        if resolved is not None:
            return resolved

        return self.workspace_root

    def _resolve_project_source_path(self, *, workspace_id: str, project_id: str) -> Path | None:
        artifacts_root = getattr(self.context_builder, "project_artifacts_root", None)
        if not isinstance(artifacts_root, Path):
            return None

        normalized_workspace, plain_project = split_scoped_project_id(
            project_id,
            fallback_workspace_id=workspace_id,
        )

        files_index = (
            artifacts_root
            / "workspaces"
            / normalized_workspace
            / plain_project
            / "raw"
            / "files_index.json"
        )
        if not files_index.exists():
            return None

        try:
            payload = json.loads(files_index.read_text(encoding="utf-8"))
        except Exception:
            return None

        raw_path = str(payload.get("project_path") or "").strip()
        if not raw_path:
            return None

        resolved = Path(raw_path).resolve()
        if not resolved.exists() or not resolved.is_dir():
            return None

        return resolved
