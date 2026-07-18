import rune

TEST_RUNE_SOURCE = """2+2
"dog" + "cat"
@chaos 1
if ("dog" > "cat")
1
else
0
end
if (0)
0
elif (2)
2
else
0
end
@chaos 500
if ("dog" > "cat")
1
else
0
end
"""

EXPECTED_OUTPUT = "4\n626\n1\n2\n0\n"


def test_run_file_golden_output(tmp_path, capsys):
    path = tmp_path / "golden.rune"
    path.write_text(TEST_RUNE_SOURCE)

    rc = rune.run_file(str(path))

    assert rc == 0
    assert capsys.readouterr().out == EXPECTED_OUTPUT


def test_run_file_missing_file_returns_error():
    rc = rune.run_file("this_file_does_not_exist.rune")
    assert rc == 1


def test_run_code_lex_error_reports_to_stderr(capsys):
    rc = rune.run_code("#")

    assert rc == 1
    err = capsys.readouterr().err
    assert "Lex error" in err


def test_run_code_oversized_integer_reports_lex_error(capsys):
    rc = rune.run_code("9" * 4_301)

    assert rc == 1
    err = capsys.readouterr().err
    assert "Lex error" in err
    assert "4300-digit limit" in err


def test_run_code_parse_error_reports_to_stderr(capsys):
    rc = rune.run_code("if (1)\n1\n")

    assert rc == 1
    err = capsys.readouterr().err
    assert "Parse error" in err


def test_repl_handles_errors_and_exits(monkeypatch, capsys):
    inputs = iter(["2+2", "#"])

    def fake_input(prompt=""):
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)

    rune.repl()

    out = capsys.readouterr().out
    assert "=> 4" in out
    assert "Lex error" in out
    assert "Goodbye!" in out


def test_run_code_verbose_formats_runtime_events(capsys):
    rc = rune.run_code("@chaos 500", verbose=True)

    assert rc == 0
    out = capsys.readouterr().out
    assert "[CHAOS] Threshold set to 500" in out


def _scripted_repl(monkeypatch, lines):
    inputs = iter(lines)

    def fake_input(prompt=""):
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)
    rune.repl()


def test_repl_state_persists_after_success(monkeypatch, capsys):
    _scripted_repl(
        monkeypatch,
        [
            "@chaos 500",
            'if ("dog" > "cat")\n1\nelse\n0\nend',
        ],
    )

    out = capsys.readouterr().out
    assert "=> 0" in out


def test_repl_state_survives_failed_evaluation_unchanged(monkeypatch, capsys):
    _scripted_repl(
        monkeypatch,
        [
            "@chaos 500",
            "#",
            'if ("dog" > "cat")\n1\nelse\n0\nend',
        ],
    )

    out = capsys.readouterr().out
    assert "Lex error" in out
    assert "=> 0" in out
