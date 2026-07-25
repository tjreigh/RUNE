# RUNE 0.8 language reference

This document defines the v0.8 language. The [README](../README.md) is the
tutorial; this page is the compact answer to “what does RUNE actually do?”

## The model

RUNE has one runtime value type: an integer. A string becomes the sum of its
Unicode code points when evaluated:

```rune
"cat"        # 312
"😀"         # 128512
"é"          # 233
"é"         # 870: no Unicode normalization
```

Top-level expression statements produce output. Assignments, `@chaos`, and
function declarations do not.

Execution is transactional. A failed evaluation produces no values or events
and preserves the state it received.

## Source

- Source is Unicode and keywords are lowercase and case-sensitive.
- `#` starts a comment through the end of the line, except inside a string.
- Strings use `"`. There are no escape sequences; backslashes are ordinary
  characters.
- Identifiers begin with a Unicode letter or `_`, followed by letters, digits,
  or `_`.
- Integer literals may be decimal or use `0b`, `0o`, and `0x`. Underscores are
  not accepted in numbers.
- Newlines normally separate statements and cannot split an expression.
- Blocks use typed endings: `end if`, `end while`, `end for`, and
  `end function`.

The reserved words are:

```text
and break chaos continue elif else end for from function
if not or return step to while
```

## Operators

Precedence runs from highest to lowest, one level per row:

| Level | Forms and operators | Associativity |
| ---: | --- | --- |
| 1 | Calls, literals, variables, grouping | — |
| 2 | `**` | Right |
| 3 | Prefix `-`, `~` | Right |
| 4 | `*`, `/`, `%` | Left |
| 5 | `+`, `-` | Left |
| 6 | `<<`, `>>` | Left |
| 7 | `&` | Left |
| 8 | `^` | Left |
| 9 | `\|` | Left |
| 10 | `<`, `>`, `<=`, `>=`, `==`, `!=` | Left |
| 11 | Prefix `not` | Right |
| 12 | `and` | Left |
| 13 | `or` | Left |

Important details:

- `/` truncates toward zero; `%` follows the dividend's sign.
- `**` is power and `^` is XOR.
- Power binds tighter than unary minus, so `-2 ** 2` is `-4`.
- Comparisons and logical operators return `1` or `0`.
- Signed bitwise operations use infinite-width two's-complement behavior.
- Division by zero, modulo by zero, negative exponents, and negative shift
  counts are runtime errors.

## Chaos

Runtime state starts with a chaos threshold of `1`. Change it with a
non-negative integer literal:

```rune
@chaos 10
```

A value is chaos-truthy when it is positive and greater than or equal to the
current threshold. Zero and negative values are always falsy.

`if`, `while`, `and`, `or`, and `not` use chaos truthiness. `and` and `or`
short-circuit, and all logical results normalize to `1` or `0`. This means a
true logical result can itself be falsy when the threshold is above `1`.

## Variables and control flow

Assignment evaluates and stores an integer immediately:

```rune
animal = "cat"
score = animal + 1
score
```

This outputs `313`. Reading an undefined variable is a runtime error.

Conditionals require parenthesized conditions:

```text
if (condition)
    statements
elif (condition)
    statements
else
    statements
end if
```

`while` reevaluates its condition before every iteration:

```text
while (condition)
    statements
end while
```

Counted loops include both endpoints:

```text
for counter from start to stop step increment
    statements
end for
```

The step defaults to `1`. Bounds and step are evaluated once. A zero step is
an error, while a step aimed away from the endpoint performs zero iterations.
The counter is loop-local and restores any variable it shadows. `break` and
`continue` affect the nearest enclosing loop.

## Functions

Functions are top-level declarations with explicit returns:

```rune
function factorial(n)
    if (n <= 1)
        return 1
    end if
    return n * factorial(n - 1)
end function

factorial(5)
```

This outputs `120`.

Declarations are hoisted within one compilation unit, allowing forward calls
and mutual recursion. Arguments evaluate from left to right. Parameters and
assignments are local to a call; persistent variables remain readable when
not shadowed, but a callee cannot read its caller's locals.

Calling an unknown function, passing the wrong number of arguments, or
reaching `end function` without a return is a runtime error.

Function declarations are not stored in runtime state. A later REPL
submission must repeat declarations it calls.

## Diagnostics and limits

Diagnostics are classified as `lex`, `parse`, `runtime`, `limit`, or
`internal`, with a source span when one is available.

Normal execution defaults to 10,000 interpreter steps, recursion depth 100,
1,000 output values, 256 variables and active bindings, 14,285-bit integers,
and 1,000 runtime events. Expression and block nesting are separately limited
to 100 levels. The web REPL also applies source, time, memory, concurrency,
response, and session limits.

Trusted local `--unbounded` execution removes interpreter budgets only. It
does not remove parser, Python, or operating-system limits.

## Compatibility before 1.0

The language is still allowed to change between minor releases. Until v1.0:

- documented breaking changes get migration notes in the
  [changelog](../CHANGELOG.md);
- patch releases should preserve documented language behavior;
- the supported Python surface is the names exported by `rune.__all__`;
- exact diagnostic wording, AST/token representation, resource accounting,
  web endpoints, and terminal formatting are not stable interfaces.

The core serialized result keeps the fields `ok`, `values`, `diagnostics`,
`events`, `state`, and `stats`. Consumers should ignore additional fields.
The public web REPL is an application rather than a versioned general-purpose
API.
