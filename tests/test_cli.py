from pathlib import Path

import rune
from limits import ExecutionLimits

TEST_RUNE_SOURCE = (
    Path(__file__).resolve().parent.parent / "test.rune"
).read_text()

EXPECTED_OUTPUT = (
    "42\n42\n25\n-3\n-2\n42\n626\n0\n1\n1\n1\n2\n1\n0\n"
    "5\n4\n3\n1\n3\n5\n1\n3\n4\n"
    "120\n"
)


def test_run_file_golden_output(tmp_path, capsys):
    path = tmp_path / "golden.rune"
    path.write_text(TEST_RUNE_SOURCE)

    rc = rune.run_file(str(path))

    assert rc == 0
    assert capsys.readouterr().out == EXPECTED_OUTPUT


def test_run_file_missing_file_returns_error():
    rc = rune.run_file("this_file_does_not_exist.rune")
    assert rc == 1


def test_run_file_accepts_trusted_unbounded_policy(tmp_path, capsys):
    path = tmp_path / "long-running.rune"
    path.write_text("for i from 1 to 10001\nend for")

    bounded_rc = rune.run_file(str(path))
    assert bounded_rc == 1
    assert "Step budget exceeded" in capsys.readouterr().err

    unbounded_rc = rune.run_file(
        str(path),
        limits=ExecutionLimits.unbounded(),
    )
    assert unbounded_rc == 0
    assert capsys.readouterr().err == ""


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


def test_run_code_interrupt_exits_cleanly_without_traceback(monkeypatch, capsys):
    def interrupted_execute(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(rune, "execute", interrupted_execute)

    rc = rune.run_code("while (1)\nend while", limits=ExecutionLimits.unbounded())

    assert rc == 130
    assert capsys.readouterr().err == "Execution interrupted.\n"


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


def test_run_code_verbose_formats_variable_assignment_event(capsys):
    rc = rune.run_code("answer = 42", verbose=True)

    assert rc == 0
    assert "[VARIABLE] answer = 42" in capsys.readouterr().out


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
            'if ("dog" > "cat")\n1\nelse\n0\nend if',
        ],
    )

    out = capsys.readouterr().out
    assert "=> 0" in out


def test_repl_variables_persist_between_inputs(monkeypatch, capsys):
    _scripted_repl(monkeypatch, ["answer = 40", "answer = answer + 2", "answer"])

    out = capsys.readouterr().out
    assert "=> 42" in out


def test_repl_state_survives_failed_evaluation_unchanged(monkeypatch, capsys):
    _scripted_repl(
        monkeypatch,
        [
            "@chaos 500",
            "#",
            'if ("dog" > "cat")\n1\nelse\n0\nend if',
        ],
    )

    out = capsys.readouterr().out
    assert "Lex error" in out
    assert "=> 0" in out


def test_main_unbounded_flag_selects_trusted_policy_for_file(monkeypatch):
    observed = {}

    def fake_run_file(filepath, **kwargs):
        observed["filepath"] = filepath
        observed["limits"] = kwargs["limits"]
        return 0

    monkeypatch.setattr(rune, "run_file", fake_run_file)
    monkeypatch.setattr(rune.sys, "argv", ["rune", "program.rune", "--unbounded"])

    assert rune.main() == 0
    assert observed["filepath"] == "program.rune"
    assert observed["limits"].is_unbounded


def test_main_remains_bounded_without_unbounded_flag(monkeypatch):
    observed = {}

    def fake_run_file(filepath, **kwargs):
        observed["limits"] = kwargs["limits"]
        return 0

    monkeypatch.setattr(rune, "run_file", fake_run_file)
    monkeypatch.setattr(rune.sys, "argv", ["rune", "program.rune"])

    assert rune.main() == 0
    assert observed["limits"] is None


def test_main_unbounded_flag_selects_trusted_policy_for_repl(monkeypatch):
    observed = {}

    def fake_repl(limits=None):
        observed["limits"] = limits

    monkeypatch.setattr(rune, "repl", fake_repl)
    monkeypatch.setattr(rune.sys, "argv", ["rune", "--repl", "--unbounded"])

    assert rune.main() == 0
    assert observed["limits"].is_unbounded
