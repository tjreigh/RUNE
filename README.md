# RUNE

RUNE (Runtime Unicode Numeric Evaluation) is a tiny tree-walking esolang where every value becomes a number and reality depends on a chaos threshold.

Run a file with:

```sh
python src/rune.py program.rune
```

Or start the interactive prompt with `python src/rune.py --repl`.

Strings collapse to the sum of their Unicode code points. Comparisons return `1` or `0`, while `@chaos` sets the minimum positive value that a conditional considers true:

```rune
"dog" + "cat"

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

The same literally true comparison takes opposite branches as reality becomes less accommodating.
