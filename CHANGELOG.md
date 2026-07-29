# Changelog

RUNE is pre-1.0. Minor releases may change the language; breaking changes get
migration notes here.

## v0.9.0 — Unreleased

Added:

- Scoped `chaos expression` / `end chaos` blocks with dynamically visible
  thresholds and guaranteed restoration across normal completion, control
  flow, runtime failures, and execution limits.
- A bounded, non-committing trace runtime with statement checkpoints, state
  deltas, dynamic function and loop context, output and event changes,
  execution statistics, remaining budgets, and explicit `return`, `break`,
  and `continue` destinations.
- Exact full-artifact trace limits, a typed public trace schema, normalized
  diagnostics referenced by error frames, and explicit artifact availability.
- An isolated `POST /debug` backend that records a trace from a normal web
  session snapshot without committing the traced program's final state.
- A browser trace player with Debug, Restart, Step Back, Step, Step Over, Step
  Out, Play/Pause, and Stop controls; reversible state, output, and event
  playback; source-span highlighting; and frame context, stack, loop,
  statistics, and budget views.

Changed:

- Runtime control flow now uses one real dynamic execution stack shared by
  language semantics and debugger observation.
- Run and Debug share source, request, rate, concurrency, session-lock,
  disposable-worker, timeout, process-resource, and response-size safeguards.
- The FastAPI adapter and browser assets now ship in the installable
  `rune_web` package, with tests organized by core, CLI, web, packaging,
  deployment, and frontend boundaries.
- Browser code and its behavior tests are authored as strict TypeScript
  modules and built with the Yarn-locked frontend toolchain before testing,
  packaging, or deployment.
- Trace control-flow linking supports nested recursive returns whose observable
  destinations coincide, and the hosted 64 KiB artifact budget accommodates
  the full walkthrough while retaining an independent response-envelope cap.

Behavior and migration notes:

- `chaos` is now reserved for scoped chaos blocks.
- Debugging may create or reuse an ordinary browser session, but a debug run
  never commits state. Reset invalidates an in-flight debug result.
- Stopping a trace or editing its source returns the browser to the last
  committed Run result. Step Over exits the innermost enclosing loop, matching
  the loop-aware debugger behavior, or advances past nested function calls
  until execution returns to the current call depth. Step Out advances until
  the current function invocation returns to its caller. Play advances at a
  visible, adjustable 0.25×–2× cadence, can be paused on the selected frame,
  and suppresses intermediate live-region announcements. Its speed control is
  shown only while playback is paused or active, and chaos-level changes receive
  a brief visual highlight. Restart rewinds the current artifact locally
  without recording another trace.
- Trace diagnostics are stored once at the artifact level; error frames refer
  to them by `diagnostic_index`.
- Before deploying over an installation whose root-owned deployer
  still imports `app` from `web/`, manually update the reviewed deployer and
  service policy as described in `deploy/README.md`.

## v0.8.0 — 2026-07-25

Added:

- `#` single-line comments.
- Parser-aware multiline terminal input.
- A saved system/light/dark page theme and four independent editor palettes.
- A shared example gallery and in-page language guide.
- CI for Python 3.12, 3.13, and 3.14.
- A versioned language reference.

Changed:

- Reworked the web REPL layout, example readability, precedence table, and
  accessibility behavior.
- Hardened packaging, deployment, worker isolation, and production smoke
  tests.

Migration notes:

- `#` now starts a comment outside strings instead of producing a lex error.
- Functions remain source-local. In the terminal REPL, submit a declaration
  and its calls together as one multiline draft.

## v0.7.0 — 2026-07-23

- Added top-level functions, calls, explicit returns, recursion, declaration
  hoisting, and isolated call-local scope.
- Added live compile-only validation to the web editor.

Migration: `function` and `return` became reserved words. Function
declarations do not persist between compilation units.

## v0.6.0 — 2026-07-22

- Added chaos-aware `while`, inclusive counted `for`, `break`, and `continue`.
- Added loop supervision, execution statistics, coverage reporting, and
  trusted local `--unbounded` execution.

Migration: loop keywords became reserved, and loops require typed endings.

## v0.5.0 — 2026-07-22

- Completed arithmetic and bitwise expressions, grouping, unary operators,
  prefixed integers, and chaos-aware logical operators.
- Required `end if` instead of bare `end`.

Migration: `/` is truncating integer division, `**` is power, `^` is XOR, and
logical operators normalize to `1` or `0`.

## v0.4.0 — 2026-07-19

- Added variables, transactional runtime state, bounded web sessions, reset,
  and runtime inspection.

## Before v0.4

The untagged early versions established RUNE's integer and Unicode-string
expressions, comparisons, `@chaos` truthiness, and `if` / `elif` / `else`.
They also introduced structured diagnostics, the embeddable evaluation API,
execution limits, the isolated web REPL, and the first public deployment.

These versions were not retained as release tags, and their commits overlap
the milestone boundaries rather than forming a clean release history. This is
a summary, not a reconstructed version-by-version changelog.
