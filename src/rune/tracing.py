"""Bounded, JSON-safe checkpoint recording for the tree-walking interpreter."""

from dataclasses import dataclass, replace
import json
from typing import Any, Literal, NotRequired, TypedDict

from .diagnostics import Diagnostic, RuneLimitError
from .limits import TraceLimits
from .runtime_state import RuntimeState


TraceFrameStatus = Literal["paused", "completed", "error"]
TraceControlFlowKind = Literal["break", "continue", "return"]
TraceDiagnosticKind = Literal["lex", "parse", "runtime", "internal", "limit"]


class _TraceLimitError(RuneLimitError):
    """Identify recorder limits without relying on diagnostic wording."""


class TracePosition(TypedDict):
    line: int
    column: int


class TraceSpan(TypedDict):
    start: TracePosition
    end: TracePosition


class TraceActive(TypedDict):
    site_id: int | None
    node_kind: str
    span: TraceSpan
    loop_instance_id: int | None


class TraceValueChange(TypedDict):
    before: int
    after: int


class TraceBindingChange(TypedDict):
    name: str
    before_exists: bool
    before: int | None
    after_exists: bool
    after: int | None
    scope_id: NotRequired[int | None]
    kind: NotRequired[str]
    label: NotRequired[str | None]


class TraceEvent(TypedDict):
    kind: str
    data: dict[str, Any]
    span: TraceSpan | None


class TraceChanges(TypedDict):
    chaos_threshold: TraceValueChange | None
    variables: list[TraceBindingChange]
    locals: list[TraceBindingChange]
    output_values: list[int]
    events: list[TraceEvent]


class TraceExecutionFrame(TypedDict):
    instance_id: int
    kind: Literal["function", "while", "for", "chaos"]
    span: TraceSpan | None
    name: NotRequired[str]
    counter: NotRequired[str]
    iteration: NotRequired[int]
    previous_chaos_threshold: NotRequired[int]
    entered_chaos_threshold: NotRequired[int]


class TraceContext(TypedDict):
    function: str | None
    call_depth: int
    call_stack: list[TraceExecutionFrame]
    call_stack_truncated: int
    loops: list[TraceExecutionFrame]


class TraceStats(TypedDict):
    steps: int
    peak_recursion_depth: int
    output_values: int
    runtime_events: int
    loop_iterations: int


class TraceBudgets(TypedDict):
    steps: int | None
    output_values: int | None
    runtime_events: int | None
    trace_frames: int
    trace_bytes: int


class TraceDiagnostic(TypedDict):
    kind: TraceDiagnosticKind
    message: str
    span: TraceSpan | None


class TraceControlFlow(TypedDict):
    kind: TraceControlFlowKind
    destination_frame: int


class TraceFrameDict(TypedDict):
    number: int
    status: TraceFrameStatus
    active: TraceActive | None
    changes: TraceChanges
    context: TraceContext
    stats: TraceStats
    budgets: TraceBudgets
    diagnostic_index: NotRequired[int]
    truncated: NotRequired[bool]
    control_flow: NotRequired[TraceControlFlow]


class TraceState(TypedDict):
    chaos_threshold: int
    variables: NotRequired[dict[str, int]]


class TraceResultDict(TypedDict):
    ok: bool
    artifact_available: bool
    diagnostics: list[TraceDiagnostic]
    base_state: TraceState | None
    frames: list[TraceFrameDict]


def _canonical_json_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class TraceFrame:
    number: int
    status: TraceFrameStatus
    active: TraceActive | None
    changes: TraceChanges
    context: TraceContext
    stats: TraceStats
    budgets: TraceBudgets
    diagnostic_index: int | None = None
    truncated: bool = False
    control_flow: TraceControlFlow | None = None

    def to_dict(self) -> TraceFrameDict:
        result = {
            "number": self.number,
            "status": self.status,
            "active": self.active,
            "changes": self.changes,
            "context": self.context,
            "stats": self.stats,
            "budgets": self.budgets,
        }
        if self.diagnostic_index is not None:
            result["diagnostic_index"] = self.diagnostic_index
        if self.truncated:
            result["truncated"] = True
        if self.control_flow is not None:
            result["control_flow"] = self.control_flow
        return result


@dataclass
class TraceResult:
    diagnostics: list[Diagnostic]
    base_state: RuntimeState | None
    frames: list[TraceFrame]
    artifact_available: bool = True

    @property
    def ok(self):
        return not self.diagnostics

    def to_dict(self) -> TraceResultDict:
        return {
            "ok": self.ok,
            "artifact_available": self.artifact_available,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "base_state": (
                self.base_state.to_dict()
                if self.base_state is not None
                else None
            ),
            "frames": [frame.to_dict() for frame in self.frames],
        }

    def artifact_json_bytes(self):
        """Canonical full artifact governed by the serialization budget."""
        if not self.artifact_available:
            return None
        return _canonical_json_bytes(self.to_dict())


class TraceRecorder:
    """Capture state at executable boundaries and encode only state changes."""

    def __init__(self, base_state, limits=None):
        self.base_state = base_state
        self.limits = limits if limits is not None else TraceLimits()
        self.diagnostics = []
        self.frames = []
        self.artifact_available = True
        self._previous = None
        self._site_ids = {}
        self._next_site_id = 1
        self._binding_changes = 0
        self._output_values = 0
        self._events = 0
        self._pending_output_values = []
        self._pending_events = []
        self._pending_control_flow = None
        self._frame_sizes = []
        self._empty_payload_bytes = self._empty_payload_size()
        self._serialized_bytes = self._empty_payload_bytes
        if self._serialized_bytes > self.limits.max_serialized_bytes:
            raise _TraceLimitError(
                "Trace serialization budget exceeded",
                None,
            )

    def _empty_payload_size(self):
        return len(_canonical_json_bytes({
            "ok": not self.diagnostics,
            "artifact_available": True,
            "diagnostics": [
                diagnostic.to_dict() for diagnostic in self.diagnostics
            ],
            "base_state": self.base_state.to_dict(),
            "frames": [],
        }))

    def _set_error_diagnostic(self, diagnostic):
        if self.diagnostics:
            raise RuntimeError("Trace diagnostic is already set")
        previous_empty_size = self._empty_payload_bytes
        self.diagnostics = [diagnostic]
        self._empty_payload_bytes = self._empty_payload_size()
        self._serialized_bytes += (
            self._empty_payload_bytes - previous_empty_size
        )

    def _site_id(self, node, kind, span):
        key = (id(node), kind, repr(span))
        if key not in self._site_ids:
            self._site_ids[key] = self._next_site_id
            self._next_site_id += 1
        return self._site_ids[key]

    @staticmethod
    def _flatten_locals(local_scopes):
        flattened = {}
        scope_meta = {}
        for scope in local_scopes:
            scope_id = scope["scope_id"]
            scope_meta[scope_id] = {
                "scope_id": scope_id,
                "kind": scope["kind"],
                "label": scope["label"],
            }
            for name, value in scope["values"].items():
                flattened[(scope_id, name)] = value
        return flattened, scope_meta

    @staticmethod
    def _mapping_changes(before, after, *, local_meta=None):
        changes = []
        for key in sorted(set(before) | set(after), key=repr):
            before_exists = key in before
            after_exists = key in after
            if before_exists and after_exists and before[key] == after[key]:
                continue
            if local_meta is None:
                name = key
                change = {"name": name}
            else:
                scope_id, name = key
                meta = local_meta.get(scope_id, {"scope_id": scope_id})
                change = {**meta, "name": name}
            change.update(
                {
                    "before_exists": before_exists,
                    "before": before.get(key),
                    "after_exists": after_exists,
                    "after": after.get(key),
                }
            )
            changes.append(change)
        return changes

    def _snapshot(self, interpreter):
        observed = interpreter.trace_snapshot()
        locals_flat, local_meta = self._flatten_locals(observed["bindings"])
        state = observed["state"]
        return {
            "chaos_threshold": state["chaos_threshold"],
            "variables": dict(state.get("variables", {})),
            "locals": locals_flat,
            "local_meta": local_meta,
            "stats": observed["stats"],
            "execution": observed["execution"],
            "execution_limits": observed["execution_limits"],
        }

    def record_output(self, value, span):
        """Accept one newly emitted value without retaining prior output."""
        if self._output_values + 1 > self.limits.max_output_values:
            raise _TraceLimitError("Trace output budget exceeded", span)
        self._output_values += 1
        self._pending_output_values.append(value)

    def record_event(self, event):
        """Accept one newly recorded event without retaining event history."""
        if self._events + 1 > self.limits.max_events:
            raise _TraceLimitError("Trace event budget exceeded", event.span)
        self._events += 1
        self._pending_events.append(event.to_dict())

    def record_control_flow(self, kind):
        """Mark the latest checkpoint as an executed non-local transfer."""
        expected_node_kind = {
            "break": "BreakNode",
            "continue": "ContinueNode",
            "return": "ReturnNode",
        }.get(kind)
        if (
            expected_node_kind is None
            or not self.frames
            or self.frames[-1].active is None
            or self.frames[-1].active["node_kind"] != expected_node_kind
        ):
            raise RuntimeError("Control-flow checkpoint is missing")
        if self._pending_control_flow is not None:
            raise RuntimeError("Control-flow destination is still pending")
        self._pending_control_flow = (len(self.frames) - 1, kind, False)

    def control_flow_destination_ready(self):
        """Allow the next checkpoint to become the transfer destination."""
        if self._pending_control_flow is None:
            raise RuntimeError("Control-flow checkpoint is missing")
        frame_index, kind, _ready = self._pending_control_flow
        self._pending_control_flow = (frame_index, kind, True)

    def _changes(self, current):
        if self._previous is None:
            before = {
                "chaos_threshold": self.base_state.chaos_threshold,
                "variables": self.base_state.variables,
                "locals": {},
                "local_meta": {},
            }
        else:
            before = self._previous

        variable_changes = self._mapping_changes(
            before["variables"], current["variables"]
        )
        combined_meta = {**before["local_meta"], **current["local_meta"]}
        local_changes = self._mapping_changes(
            before["locals"],
            current["locals"],
            local_meta=combined_meta,
        )
        self._binding_changes += len(variable_changes) + len(local_changes)
        if self._binding_changes > self.limits.max_binding_changes:
            raise _TraceLimitError(
                "Trace binding-change budget exceeded",
                None,
            )

        return {
            "chaos_threshold": {
                "before": before["chaos_threshold"],
                "after": current["chaos_threshold"],
            },
            "variables": variable_changes,
            "locals": local_changes,
            "output_values": list(self._pending_output_values),
            "events": list(self._pending_events),
        }

    @staticmethod
    def _bounded_stack(call_stack, maximum):
        if len(call_stack) <= maximum:
            return list(call_stack), 0
        if maximum == 1:
            return [call_stack[-1]], len(call_stack) - 1
        return [call_stack[0], *call_stack[-(maximum - 1):]], (
            len(call_stack) - maximum
        )

    def _context(self, snapshot):
        execution = snapshot["execution"]
        call_frames = [
            frame for frame in execution if frame["kind"] == "function"
        ]
        stack, truncated = self._bounded_stack(
            call_frames,
            self.limits.max_stack_frames,
        )
        return {
            "function": stack[-1]["name"] if stack else None,
            "call_depth": len(call_frames),
            "call_stack": stack,
            "call_stack_truncated": truncated,
            "loops": [
                frame
                for frame in execution
                if frame["kind"] in {"for", "while"}
            ],
        }

    def _budgets(self, snapshot):
        execution = snapshot["execution_limits"]
        stats = snapshot["stats"]

        def remaining(maximum, used):
            return None if maximum is None else max(0, maximum - used)

        return {
            "steps": remaining(execution["max_steps"], stats["steps"]),
            "output_values": remaining(
                execution["max_output_values"], stats["output_values"]
            ),
            "runtime_events": remaining(
                execution["max_events"], stats["runtime_events"]
            ),
            "trace_frames": max(
                0, self.limits.max_frames - len(self.frames)
            ),
            "trace_bytes": max(
                0, self.limits.max_serialized_bytes - self._serialized_bytes
            ),
        }

    def capture(
        self,
        interpreter,
        *,
        node=None,
        kind=None,
        span=None,
        status="paused",
        diagnostic_index=None,
        terminal=False,
        loop_instance_id=None,
    ):
        frame_ceiling = (
            self.limits.max_frames
            if terminal
            else max(0, self.limits.max_frames - 1)
        )
        if len(self.frames) >= frame_ceiling:
            raise _TraceLimitError("Trace frame budget exceeded", span)

        current = self._snapshot(interpreter)
        try:
            changes = self._changes(current)
        except RuneLimitError as exc:
            if exc.diagnostic.span is None:
                exc.diagnostic.span = span
            raise

        active = None
        if span is not None:
            active = {
                "site_id": self._site_id(node, kind, span),
                "node_kind": kind,
                "span": span.to_dict(),
                "loop_instance_id": loop_instance_id,
            }
        frame = TraceFrame(
            number=len(self.frames),
            status=status,
            active=active,
            changes=changes,
            context=self._context(current),
            stats=current["stats"],
            budgets=self._budgets(current),
            diagnostic_index=diagnostic_index,
        )
        encoded_size = len(_canonical_json_bytes(frame.to_dict()))
        linked_frame, linked_size_delta = self._linked_control_frame(
            frame.number
        )
        delimiter_size = 1 if self.frames else 0
        if (
            self._serialized_bytes
            + linked_size_delta
            + delimiter_size
            + encoded_size
            > self.limits.max_serialized_bytes
        ):
            raise _TraceLimitError(
                "Trace serialization budget exceeded",
                span,
            )
        self._apply_control_link(linked_frame, linked_size_delta)
        self.frames.append(frame)
        added_size = delimiter_size + encoded_size
        self._frame_sizes.append(added_size)
        self._serialized_bytes += added_size
        self._previous = current
        self._pending_output_values.clear()
        self._pending_events.clear()

    def _linked_control_frame(self, destination_number):
        if self._pending_control_flow is None:
            return None, 0
        frame_index, kind, ready = self._pending_control_flow
        if not ready:
            return None, 0
        frame = self.frames[frame_index]
        linked = replace(
            frame,
            control_flow={
                "kind": kind,
                "destination_frame": destination_number,
            },
        )
        size_delta = (
            len(_canonical_json_bytes(linked.to_dict()))
            - len(_canonical_json_bytes(frame.to_dict()))
        )
        return linked, size_delta

    def _apply_control_link(self, linked_frame, size_delta):
        if linked_frame is None:
            return
        frame_index, _kind, _ready = self._pending_control_flow
        self.frames[frame_index] = linked_frame
        self._frame_sizes[frame_index] += size_delta
        self._serialized_bytes += size_delta
        self._pending_control_flow = None

    def finish_success(self, interpreter):
        self.capture(
            interpreter,
            status="completed",
            terminal=True,
        )

    def finish_error(self, interpreter, error):
        diagnostic = error.diagnostic
        self._set_error_diagnostic(diagnostic)
        if isinstance(error, _TraceLimitError):
            return self._append_truncated_error(interpreter, diagnostic)
        try:
            self.capture(
                interpreter,
                kind="error",
                span=diagnostic.span,
                status="error",
                diagnostic_index=0,
                terminal=True,
            )
        except RuneLimitError:
            return self._append_truncated_error(interpreter, diagnostic)
        return True

    def _drop_last_frame(self):
        if not self.frames:
            return
        dropped_index = len(self.frames) - 1
        self.frames.pop()
        self._serialized_bytes -= self._frame_sizes.pop()
        if (
            self._pending_control_flow is not None
            and self._pending_control_flow[0] == dropped_index
        ):
            self._pending_control_flow = None

    def _append_truncated_error(self, interpreter, diagnostic):
        """Fit an explicit terminal marker without exceeding trace limits.

        Tail frames may be discarded to make room. The marker deliberately
        carries no state delta, so the retained prefix remains replayable.
        """
        current = self._snapshot(interpreter)
        active = None
        if diagnostic.span is not None:
            active = {
                "site_id": None,
                "node_kind": "error",
                "span": diagnostic.span.to_dict(),
                "loop_instance_id": None,
            }

        while True:
            terminal = TraceFrame(
                number=len(self.frames),
                status="error",
                active=active,
                changes={
                    "chaos_threshold": None,
                    "variables": [],
                    "locals": [],
                    "output_values": [],
                    "events": [],
                },
                context={
                    "function": None,
                    "call_depth": 0,
                    "call_stack": [],
                    "call_stack_truncated": 0,
                    "loops": [],
                },
                stats=current["stats"],
                budgets={
                    "steps": 0,
                    "output_values": 0,
                    "runtime_events": 0,
                    "trace_frames": max(
                        0, self.limits.max_frames - len(self.frames) - 1
                    ),
                    "trace_bytes": max(
                        0,
                        self.limits.max_serialized_bytes
                        - self._serialized_bytes,
                    ),
                },
                diagnostic_index=0,
                truncated=True,
            )
            encoded_size = len(_canonical_json_bytes(terminal.to_dict()))
            linked_frame, linked_size_delta = self._linked_control_frame(
                terminal.number
            )
            delimiter_size = 1 if self.frames else 0
            fits_frames = len(self.frames) < self.limits.max_frames
            fits_bytes = (
                self._serialized_bytes
                + linked_size_delta
                + delimiter_size
                + encoded_size
                <= self.limits.max_serialized_bytes
            )
            if fits_frames and fits_bytes:
                self._apply_control_link(linked_frame, linked_size_delta)
                self.frames.append(terminal)
                added_size = delimiter_size + encoded_size
                self._frame_sizes.append(added_size)
                self._serialized_bytes += added_size
                return True
            if not self.frames:
                if self._serialized_bytes > self.limits.max_serialized_bytes:
                    self.artifact_available = False
                return False
            self._drop_last_frame()
