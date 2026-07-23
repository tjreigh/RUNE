# RUNE

RUNE (Runtime Unicode Numeric Evaluation) is a tiny esolang where every value is
an integer and truthiness is chaotic. Strings collapse to Unicode code-point
sums, and a configurable chaos threshold means even `1` can be falsy.

Try it in the public web REPL: [rune.tjreigh.mobi](https://rune.tjreigh.mobi/).

## The language

### Chaos logic and conditionals

`@chaos` sets the minimum positive value that a conditional considers true:

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

The comparison is mathematically true both times and therefore returns `1`, but
`1` stops being chaos-truthy when the threshold reaches `500`. Conditional
blocks use typed terminators such as `end if`; bare `end` is invalid.

Logical operators use the same chaos truthiness, return normalized `1` or `0`,
and short-circuit their right operand:

```rune
@chaos 1
0 and missing
5 or missing
not 0
```

This outputs `0`, `1`, and `1`. Neither reference to the undefined variable
`missing` is evaluated. Normalization deliberately preserves the joke at higher
thresholds: with `@chaos 10`, `5 or 20` returns `1`, even though that resulting
`1` is itself chaos-falsy.

### Expressions

Integer literals may be decimal or use binary, octal, and hexadecimal prefixes:

```rune
0b101010
0o52
0x2A
```

Each expression above evaluates to `42`. Parentheses group expressions, `**`
means power, and `^` means bitwise XOR. Precedence runs from low to high:

| Precedence | Operators |
| --- | --- |
| Lowest | `or` |
|  | `and` |
|  | `not` |
|  | `<`, `>`, `<=`, `>=`, `==`, `!=` |
|  | `\|` |
|  | `^` |
|  | `&` |
|  | `<<`, `>>` |
|  | `+`, `-` |
|  | `*`, `/`, `%` |
|  | Prefix `-`, `~` |
|  | `**` |
| Highest | Function calls, literals, variables, strings, and grouping |

Binary operators are left-associative except for right-associative power. Power
binds tighter than unary minus, so `-2 ** 2` is `-4`, while `(-2) ** 2` is `4`.
Division truncates toward zero and remainder follows the dividend's sign.
Negative exponents and negative shift counts are runtime errors. Signed bitwise
operations use infinite two's-complement semantics.

### Unicode arithmetic

A string's value is the sum of its Unicode code points, so emoji participate in
ordinary arithmetic:

```rune
face = "😀"
rocket = "🚀"
rocket - face
```

This outputs `128`. RUNE deliberately operates on code points rather than
displayed characters: joined emoji include their joiner and component code
points, and no Unicode normalization is performed. Visually equivalent text
such as precomposed `"é"` and decomposed `"é"` can therefore have different
numeric values.

### Variables

Assign an expression with `name = expression` and use the name in later
expressions:

```rune
animal = "cat"
score = animal + 1
score
```

This outputs `313`: strings collapse to the sum of their Unicode code points,
so `"cat"` becomes `312` before it is stored. Assignment always evaluates and
collapses its right-hand side immediately, variables contain only integers, and
assignment itself produces no output. Reading a name that has not been assigned
is a runtime error.

Names begin with a letter or underscore and may then contain letters, digits,
or underscores. Language keywords, including `if`, `while`, `for`, `function`,
`return`, `break`, `continue`, and `chaos`, are reserved.

Variables persist between successful inputs in the terminal REPL and within an
expiring browser session in the web REPL. A failed, timed-out, or rejected
evaluation does not commit partial variable or chaos changes. Reset discards the
web session.

### Loops

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
Loop blocks use typed endings: `end while` and `end for`.

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
right, and declarations are available throughout their compilation unit so
functions can call themselves or one another. Calling an unknown function,
passing the wrong number of arguments, or reaching `end function` without a
`return` is a runtime error.

Parameters shadow persistent variables. Any assignment made inside a function
is local to that call, including assignment to a name that also exists in the
session; global variables remain readable when they are not shadowed. Local
frames disappear on return or failure. Function declarations are source-local
and are not stored in terminal or browser session state, so a later input must
include declarations it calls. Recursive calls consume the same step,
recursion, variable, integer, event, and wall-clock budgets as other work.

### Can RUNE run forever?

In theory, absolutely. Variables, arithmetic, conditionals, and `while` are
enough to make RUNE Turing-complete: it can express any computation if you give
it unlimited time and absurdly large integers.

The public web REPL does not make that promise. It limits work, memory, output,
events, and wall-clock time so one chaotic program cannot eat the server.
Trusted local runs can remove RUNE's interpreter budgets explicitly:

```sh
.venv/bin/rune program.rune --unbounded
```

Normal command-line and REPL runs remain bounded. `--unbounded` allows a
program to run forever or exhaust host resources, and it does not remove parser
safeguards or limits imposed by Python and the operating system. RUNE code and
browser requests can never turn the limits off themselves.

## Run it (locally)

RUNE requires Python 3.12 or newer.

```sh
scripts/setup.sh
.venv/bin/rune test.rune
```

The editable install created by `scripts/setup.sh` also exposes the public
runtime API as `import rune` and supports `python -m rune`. Start the terminal
REPL with `.venv/bin/rune --repl`, or launch the web REPL with:

```sh
scripts/run-web.sh
```

Then open <http://127.0.0.1:8000/>.

Expand **Show internals** beneath the output to inspect committed variables and
the chaos threshold, runtime events from the latest evaluation, and execution
statistics. Failed evaluations show the state that remained committed rather
than partial working changes.

Run the test suite with `scripts/test.sh`. Extra arguments are passed to pytest,
so `scripts/test.sh -k isolation` works too.

Generate terminal and HTML line/branch coverage reports with
`scripts/coverage.sh`. Extra pytest arguments are also supported, such as
`scripts/coverage.sh -k interpreter`. Open `htmlcov/index.html` to browse the
HTML report.

## Deployment

The VPS deployment uses Uvicorn behind Caddy and systemd. See the [deployment guide](deploy/README.md) for initial setup and updates.
