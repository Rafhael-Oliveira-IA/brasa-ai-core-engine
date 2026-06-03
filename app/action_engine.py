from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.context_builder import ContextBuilder
from app.contracts import (
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
    RequestEnvelope,
    RetrievalResult,
    ValidationSeverity,
)
from app.memory.repository import MemoryRepository


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

        targets = ordered_targets[: request.max_actions]
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

        for item in reversed(operations):
            op_type = str(item.get("op") or "")
            target = str(item.get("target") or "")
            backup = str(item.get("backup") or "")

            target_path = (self.workspace_root / target).resolve()

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
        for patch in patches:
            if patch.find not in updated:
                raise ValueError("Patch find text not found in file.")
            if patch.replace_all:
                updated = updated.replace(patch.find, patch.replace)
            else:
                updated = updated.replace(patch.find, patch.replace, 1)

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
    ) -> None:
        self.context_builder = context_builder
        self.memory_repository = memory_repository
        self.workspace_root = workspace_root.resolve()
        self.backup_root = backup_root.resolve()
        self.blocked_path_prefixes = tuple(item.strip().replace("\\", "/") for item in blocked_path_prefixes if item)
        self.allow_delete = allow_delete
        self.max_file_bytes = max_file_bytes

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
        _, retrieval = self.context_builder.build(envelope)
        plan = self.planner.plan(request=request, retrieval=retrieval)
        return plan, retrieval

    def execute(self, request: ActionExecuteRequest) -> ActionExecutionReport:
        validation = self.validator.validate(
            plan=request.plan,
            workspace_root=self.workspace_root,
            blocked_path_prefixes=self.blocked_path_prefixes,
            allow_high_risk=request.options.allow_high_risk,
            allow_delete=self.allow_delete,
            strict_for_execution=not request.options.dry_run,
            max_file_bytes=self.max_file_bytes,
        )

        report = self.executor.execute(
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
