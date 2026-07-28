import os
from pathlib import Path
import subprocess
import sys
import tomllib

import rune


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_public_package_exports_runtime_api():
    result = rune.evaluate("2+2")

    assert result.ok
    assert result.values == [4]
    assert rune.ExecutionLimits().max_steps == 10_000
    assert rune.TraceFrame.__annotations__["active"] == (
        rune.TraceActive | None
    )
    assert rune.TraceFrame.__annotations__["changes"] is rune.TraceChanges
    assert rune.TraceFrame.__annotations__["context"] is rune.TraceContext
    assert rune.TraceFrame.__annotations__["budgets"] is rune.TraceBudgets
    assert rune.TraceFrame.__annotations__["control_flow"] == (
        rune.TraceControlFlow | None
    )
    assert rune.TraceResult.to_dict.__annotations__["return"] is (
        rune.TraceResultDict
    )
    assert rune.TraceResult.__annotations__["artifact_available"] is bool


def test_project_declares_src_layout_packages_static_assets_and_console_command():
    with (REPO_ROOT / "pyproject.toml").open("rb") as project_file:
        project = tomllib.load(project_file)

    assert project["build-system"]["build-backend"] == "setuptools.build_meta"
    assert project["project"]["scripts"]["rune"] == "rune.cli:main"
    assert project["tool"]["setuptools"]["packages"]["find"]["where"] == [
        "src"
    ]
    assert project["tool"]["setuptools"]["package-data"]["rune_web"] == [
        "static/*"
    ]
    assert project["tool"]["pytest"]["ini_options"]["pythonpath"] == ["src"]


def test_python_m_rune_executes_a_program_from_source_tree(tmp_path):
    program = tmp_path / "answer.rune"
    program.write_text("6*7")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO_ROOT / "src")

    completed = subprocess.run(
        [sys.executable, "-m", "rune", str(program)],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout == "42\n"
    assert completed.stderr == ""


def test_python_m_rune_help_uses_installed_command_name(tmp_path):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO_ROOT / "src")

    completed = subprocess.run(
        [sys.executable, "-m", "rune", "--help"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout.startswith("usage: rune ")
