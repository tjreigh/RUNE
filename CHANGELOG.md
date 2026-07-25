# Changelog

RUNE is pre-1.0. Minor releases may change the language; breaking changes get
migration notes here.

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
