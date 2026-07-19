# RUNE

RUNE (Runtime Unicode Numeric Evaluation) is a tiny tree-walking esolang where every value becomes a number and reality depends on a chaos threshold.

Strings collapse to the sum of their Unicode code points. Comparisons return `1` or `0`, while `@chaos` sets the minimum positive value that a conditional considers true:

```rune
@chaos 1
if ("dog" > "cat")
1
else
0
end

@chaos 500
if ("dog" > "cat")
1
else
0
end
```

The comparison is true both times, but `1` stops being truthy when the chaos threshold reaches `500`.

## Variables

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
or underscores. Keywords such as `if`, `else`, `end`, and `chaos` are reserved.

Variables persist between successful inputs in the terminal REPL and within an
expiring browser session in the web REPL. A failed, timed-out, or rejected
evaluation does not commit partial variable or chaos changes. Reset discards the
web session.

## Run it

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

Run the test suite with `scripts/test.sh`. Extra arguments are passed to pytest, so `scripts/test.sh -k isolation` works too.

## Deployment

The VPS deployment uses Uvicorn behind Caddy and systemd. See the [deployment guide](deploy/README.md) for initial setup and updates.
