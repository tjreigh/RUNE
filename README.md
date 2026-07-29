# RUNE

RUNE (Runtime Unicode Numeric Evaluation) is a tiny esolang where every value
is an integer and truthiness is chaotic. Strings collapse to Unicode code-point
sums, and a configurable chaos threshold means even `1` can be falsy.

Try it in the public web REPL:
[rune.tjreigh.mobi](https://rune.tjreigh.mobi/).

## Quick start

RUNE requires Python 3.12 or newer. Building the browser frontend from a source
checkout also requires Node.js 22 or newer and Yarn 1.22.22.

```sh
scripts/setup.sh
.venv/bin/rune examples/full.rune
```

`scripts/setup.sh` installs the locked frontend tools, builds the TypeScript
sources, and creates an editable Python installation. The installation exposes
the `rune` command, supports `python -m rune`, and makes the public runtime API
available as `import rune`.

> [!NOTE]
> The setup script creates a project-local virtual environment at `.venv`.
> Activation is optional because the commands in this README invoke its
> binaries directly. If you prefer an activated shell, use:
>
> ```sh
> source .venv/bin/activate
> rune examples/full.rune
> ```

Start the terminal REPL with:

```sh
.venv/bin/rune --repl
```

Complete single-line programs execute immediately. Incomplete expressions and
typed blocks use the `...>` continuation prompt; submit a complete multiline
draft with a blank line. Ctrl+C clears an active draft without changing
committed variables or chaos state, and exits when the prompt is idle.

Start the local web REPL with:

```sh
scripts/run-web.sh
```

Then open <http://127.0.0.1:8000/>.

## Examples and reference

The terminal and browser use the same canonical programs:

- [Hello, arithmetic](examples/smoke.rune)
- [Variables](examples/variables.rune)
- [Expressions](examples/expressions.rune)
- [Chaos-aware logic](examples/logic.rune)
- [Chaos thresholds and scopes](examples/chaos.rune)
- [Loops](examples/loops.rune)
- [Functions and recursion](examples/functions.rune)
- [Full language walkthrough](examples/full.rune)

For the complete specification and release history, see the
[language reference](docs/language-reference.md) and
[changelog](CHANGELOG.md).

## Language tour

### Chaos and truth

`@chaos` sets the persistent minimum positive value that a conditional
considers true:

```rune
@chaos 1
if ("dog" > "cat")
  1
else
  0
end if

@chaos 500
if ("dog" > "cat")
  1
else
  0
end if
```

The comparison is mathematically true both times and therefore returns `1`,
but `1` stops being chaos-truthy when the threshold reaches `500`.

Logical operators use the same chaos truthiness, return normalized `1` or `0`,
and short-circuit their right operand:

```rune
@chaos 1
0 and missing
5 or missing
not 0
```

This outputs `0`, `1`, and `1`. Neither undefined reference is evaluated.
Normalization deliberately preserves the joke at higher thresholds: with
`@chaos 10`, `5 or 20` returns `1`, even though that result is itself
chaos-falsy.

Use `chaos expression` / `end chaos` when a threshold should apply only to one
dynamic scope:

```rune
@chaos 1

chaos 500
  if (1)
    99
  else
    0
  end if
end chaos

if (1)
  99
else
  0
end if
```

This outputs `0`, then `99`. A chaos block evaluates its threshold expression
once, makes it visible to nested blocks and called functions, and restores the
surrounding threshold afterward. Nested blocks restore in stack order.
Restoration also occurs across `return`, `break`, `continue`, runtime errors,
and execution limits. An `@chaos` inside the block changes only its temporary
threshold.

### Integer expressions and Unicode

Integer literals may be decimal or use binary, octal, and hexadecimal
prefixes:

```rune
0b101010
0o52
0x2A
```

Each expression evaluates to `42`. Parentheses group expressions, `**` means
power, and `^` means bitwise XOR. Precedence runs from high to low:

| Precedence | Operators |
| --- | --- |
| Highest | Function calls, literals, variables, strings, and grouping |
|  | `**` |
|  | Prefix `-`, `~` |
|  | `*`, `/`, `%` |
|  | `+`, `-` |
|  | `<<`, `>>` |
|  | `&` |
|  | `^` |
|  | `\|` |
|  | `<`, `>`, `<=`, `>=`, `==`, `!=` |
|  | `not` |
|  | `and` |
| Lowest | `or` |

Binary operators are left-associative except for right-associative power.
Power binds tighter than unary minus, so `-2 ** 2` is `-4`, while
`(-2) ** 2` is `4`. Division truncates toward zero and remainder follows the
dividend's sign. Negative exponents and negative shift counts are runtime
errors. Signed bitwise operations use infinite two's-complement semantics.

A string's value is the sum of its Unicode code points, so emoji participate
in ordinary arithmetic:

```rune
face = "😀"
rocket = "🚀"
rocket - face
```

This outputs `128`. RUNE operates on code points rather than displayed
characters: joined emoji include their joiner and component code points, and
no Unicode normalization is performed. Visually equivalent text such as
precomposed `"é"` and decomposed `"é"` can have different values.

### Variables and comments

Assign an expression with `name = expression` and use the name in later
expressions:

```rune
animal = "cat"
score = animal + 1
score
```

This outputs `313`. Assignment evaluates and collapses its right-hand side
immediately, variables contain only integers, and assignment itself produces
no output. Reading an undefined name is a runtime error.

Names begin with a letter or underscore and may then contain letters, digits,
or underscores. Keywords such as `if`, `while`, `for`, `function`, `return`,
`break`, `continue`, and `chaos` are reserved.

`#` begins a line comment, while `#` inside a string remains part of that
string:

```rune
# Strings become integers when evaluated.
animal = "cat"  # 99 + 97 + 116
"#"             # the code-point value 35
```

Variables persist between successful terminal REPL inputs and within an
expiring browser session. Failed, timed-out, and rejected evaluations never
commit partial variable or chaos changes. Reset discards the browser session.

### Loops and control flow

Blocks use typed terminators such as `end if`, `end while`, `end for`,
`end chaos`, and `end function`; bare `end` is invalid.

`while` checks chaos truthiness before every iteration. This loop outputs `5`,
`4`, and `3`, then stops because `2` falls below the threshold:

```rune
@chaos 3
count = 5
while (count)
  count
  count = count - 1
end while
```

Counted loops include both endpoints. Their bounds and optional step are
evaluated once, and the counter exists only inside the loop:

```rune
for i from 1 to 5 step 2
  i
end for
```

This outputs `1`, `3`, and `5`. The default step is `1`; a negative step counts
down, a step aimed away from the endpoint runs zero times, and zero is an
error. `break` exits the nearest loop and `continue` starts its next iteration.

### Functions and local scope

Declare a function at the top level with named parameters and return one value
explicitly:

```rune
function factorial(n)
  if (n <= 1)
    return 1
  end if
  return n * factorial(n - 1)
end function

factorial(5)
```

This outputs `120`. Calls are expressions, arguments evaluate from left to
right, and declarations are hoisted within their compilation unit. Calling an
unknown function, passing the wrong number of arguments, or reaching
`end function` without a return is a runtime error.

Parameters shadow persistent variables. Assignments inside a function are
local to that call; unshadowed global variables remain readable. Local frames
disappear on return or failure. Function declarations are source-local, so a
later input must repeat any declaration it calls. Recursive calls consume the
same finite budgets as other work.

### Execution limits

Variables, arithmetic, conditionals, and `while` make the language
Turing-complete when given unlimited resources. Ordinary CLI runs and the
public web REPL deliberately limit work, memory, output, events, and wall-clock
time.

Trusted local runs can remove RUNE's interpreter budgets explicitly:

```sh
.venv/bin/rune program.rune --unbounded
```

`--unbounded` can run forever or exhaust host resources. It does not remove
parser safeguards or limits imposed by Python and the operating system. RUNE
source and browser requests can never disable hosted limits.

## Web debugger

Choose **Debug** to record one bounded, non-committing execution. The browser
replays that recording locally; no untrusted worker remains paused while you
inspect it.

Use **Step** to enter calls, **Step Back** to reverse one frame, and **Step
Out** to return from the current invocation. Within a loop, **Step Over**
advances beyond the innermost enclosing loop. Outside a loop, it skips nested
function calls until execution returns to the current call depth.

**Play** advances through the remaining frames at an adjustable 0.25×–2× rate
and becomes **Pause** during playback. **Restart** rewinds the same recording
without running the program again. **Stop** or a source edit returns to the
last committed Run result.

The highlighted source span is the next statement to execute. Chaos, output,
variables, locals, events, call and loop context, statistics, and remaining
budgets show work completed before that statement. The chaos indicator briefly
highlights when its value changes. Expand **Runtime internals** to inspect the
committed Run state or selected trace frame.

## Development

Run every frontend and Python test with:

```sh
scripts/test.sh
```

Extra arguments are passed to pytest, so `scripts/test.sh -k isolation` works.
Generate terminal and HTML line/branch coverage with
`scripts/coverage.sh`; extra pytest arguments work there as well. Open
`htmlcov/index.html` for the HTML report.

For frontend-only work:

```sh
yarn typecheck
yarn build
yarn test
```

Browser and test sources are strict TypeScript. Generated browser modules live
under `src/rune_web/static/build/`; compiled tests live under
`build/frontend-tests/`. Both directories are deliberately ignored by Git.

## Project layout

The installable Python packages live under `src/`. `rune` contains the
standard-library-only language core and CLI; `rune_web` contains the FastAPI
adapter, process isolation, sessions, and built browser assets.

TypeScript browser sources live under `frontend/src`. Tests mirror the project
boundaries under `tests/core`, `tests/cli`, `tests/web`, `tests/packaging`,
`tests/deployment`, and `tests/frontend`. Language examples and documentation
are top-level resources. Operational configuration lives in `deploy`, and
repeatable development and deployment commands live in `scripts`.

## Deployment

Production runs Uvicorn behind Caddy and systemd. See the
[deployment guide](deploy/README.md) for initial setup, updates, rollback, and
smoke testing.
