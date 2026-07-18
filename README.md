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

Run the test suite with `scripts/test.sh`. Extra arguments are passed to pytest, so `scripts/test.sh -k isolation` works too.

## Deployment

The VPS deployment uses Uvicorn behind Caddy and systemd. See the [deployment guide](deploy/README.md) for initial setup and updates.
