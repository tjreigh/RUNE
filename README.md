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
| Highest | Literals, variables, strings, and grouping |

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
or underscores. Language keywords, including `if`, `else`, `end`, `and`, `or`,
`not`, and `chaos`, are reserved.

Variables persist between successful inputs in the terminal REPL and within an
expiring browser session in the web REPL. A failed, timed-out, or rejected
evaluation does not commit partial variable or chaos changes. Reset discards the
web session.

## Run it (locally)

RUNE requires Python 3.12 or newer.

```sh
scripts/setup.sh
.venv/bin/python src/rune.py test.rune
```

Start the terminal REPL with `.venv/bin/python src/rune.py --repl`, or launch the web REPL with:

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

## Deployment

The VPS deployment uses Uvicorn behind Caddy and systemd. See the [deployment guide](deploy/README.md) for initial setup and updates.
