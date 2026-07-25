#!/usr/bin/env python3
"""
RUNE (Runtime Unicode Numeric Evaluation)
A language where everything collapses to ASCII sums

Usage:
    rune <file.rune>               # Run a RUNE file
    rune <file.rune> --verbose     # Show execution details
    rune <file.rune> --show-ast    # Show Abstract Syntax Tree
    rune <file.rune> --show-tokens # Show token stream
    rune <file.rune> --unbounded   # Disable interpreter budgets
    rune --repl                    # Interactive REPL mode
"""

import sys
import argparse
from enum import Enum
from pathlib import Path

from .runtime import RuntimeState, compile_source, execute
from .diagnostics import RuneError, Diagnostic, DiagnosticKind
from .limits import ExecutionLimits

_ERROR_LABELS = {
    DiagnosticKind.LEX: "Lex error",
    DiagnosticKind.PARSE: "Parse error",
    DiagnosticKind.RUNTIME: "Runtime error",
    DiagnosticKind.INTERNAL: "Internal error",
    DiagnosticKind.LIMIT: "Execution limit",
}


class _ReplInputStatus(Enum):
    EMPTY = "empty"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"


def _compile_repl_input(source):
    """Classify one terminal draft and retain a successful compilation."""
    try:
        return _ReplInputStatus.COMPLETE, compile_source(source)
    except RuneError as error:
        if (
            error.diagnostic.kind == DiagnosticKind.PARSE
            and error.diagnostic.message == "Empty program"
        ):
            return _ReplInputStatus.EMPTY, error
        if error.incomplete:
            return _ReplInputStatus.INCOMPLETE, error
        return _ReplInputStatus.INVALID, error


def format_diagnostic(diag: Diagnostic) -> str:
    """Render a structured diagnostic for terminal output."""
    return f"{_ERROR_LABELS[diag.kind]}: {diag.format()}"


def format_error(err: RuneError) -> str:
    """Render a structured RUNE diagnostic raised as an exception."""
    return format_diagnostic(err.diagnostic)


def format_event(event) -> str:
    """Render a runtime event for --verbose output."""
    if event.kind == "chaos_threshold_changed":
        return f"[CHAOS] Threshold set to {event.data['threshold']}"
    if event.kind == "variable_assigned":
        return f"[VARIABLE] {event.data['name']} = {event.data['value']}"
    return f"[{event.kind.upper()}] {event.data}"


def run_file(
    filepath,
    show_tokens=False,
    show_ast=False,
    verbose=False,
    limits=None,
):
    """Execute a RUNE file"""
    # Read the file
    try:
        with open(filepath, 'r') as f:
            code = f.read()
    except FileNotFoundError:
        print(f"Error: File '{filepath}' not found")
        return 1
    except Exception as e:
        print(f"Error reading file: {e}")
        return 1
    
    # Execute the code
    return run_code(code, filepath, show_tokens, show_ast, verbose, limits)


def run_code(
    code,
    source_name="<input>",
    show_tokens=False,
    show_ast=False,
    verbose=False,
    limits=None,
):
    """Execute RUNE code string"""
    if not code.strip():
        return 0
    
    try:
        program = compile_source(code)
    except KeyboardInterrupt:
        print("Execution interrupted.", file=sys.stderr)
        return 130
    except RuneError as e:
        print(format_error(e), file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected internal error: {e}", file=sys.stderr)
        return 1

    if show_tokens:
        print(f"\n{'='*60}")
        print(f"TOKENS from {source_name}")
        print(f"{'='*60}")
        for i, token in enumerate(program.tokens[:-1]):  # Skip EOF
            print(f"  {i}: {token}")
        print()

    if show_ast:
        print(f"\n{'='*60}")
        print(f"AST from {source_name}")
        print(f"{'='*60}")
        print(f"  {program.ast}")
        print()

    if verbose:
        print(f"\n{'='*60}")
        print(f"EXECUTION of {source_name}")
        print(f"{'='*60}")

    try:
        result = execute(program, limits=limits)
    except KeyboardInterrupt:
        print("Execution interrupted.", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Unexpected internal error: {e}", file=sys.stderr)
        return 1

    if verbose:
        for event in result.events:
            print(format_event(event))

    if not result.ok:
        for diag in result.diagnostics:
            print(format_diagnostic(diag), file=sys.stderr)
        return 1

    for value in result.values:
        print(value)

    return 0


def repl(limits=None):
    """Interactive REPL mode"""
    print("RUNE Interactive REPL")
    print("Complete lines run immediately; blank line runs a multiline draft.")
    print("Ctrl+C clears a draft or exits when idle. Ctrl+D exits.")
    print("=" * 60)

    state = RuntimeState()
    draft = ""
    draft_status = None
    draft_program = None

    while True:
        try:
            line = input("...> " if draft else "rune> ")

            if not draft and not line.strip():
                continue

            if draft and not line and draft_status == _ReplInputStatus.COMPLETE:
                program = draft_program
                draft = ""
                draft_status = None
                draft_program = None
            else:
                candidate = line if not draft else f"{draft}\n{line}"
                status, compiled_or_error = _compile_repl_input(candidate)

                # An expression may be incomplete at the end of one terminal
                # line even though RUNE newlines normally separate statements.
                # If preserving the newline makes the draft invalid, retry the
                # new fragment as whitespace continuation.
                if (
                    draft
                    and draft_status == _ReplInputStatus.INCOMPLETE
                    and status == _ReplInputStatus.INVALID
                ):
                    continued = f"{draft} {line}"
                    continued_status, continued_result = _compile_repl_input(
                        continued
                    )
                    if continued_status in {
                        _ReplInputStatus.COMPLETE,
                        _ReplInputStatus.INCOMPLETE,
                    }:
                        candidate = continued
                        status = continued_status
                        compiled_or_error = continued_result

                if status == _ReplInputStatus.EMPTY:
                    draft = ""
                    draft_status = None
                    draft_program = None
                    continue
                if status == _ReplInputStatus.INVALID:
                    print(format_error(compiled_or_error))
                    draft = ""
                    draft_status = None
                    draft_program = None
                    continue
                if status == _ReplInputStatus.INCOMPLETE or draft:
                    draft = candidate
                    draft_status = status
                    draft_program = (
                        compiled_or_error
                        if status == _ReplInputStatus.COMPLETE
                        else None
                    )
                    continue

                program = compiled_or_error

            result = execute(
                program,
                state=state,
                limits=limits,
            )

            if result.ok:
                state = result.state
                for value in result.values:
                    print(f"=> {value}")
            else:
                for diag in result.diagnostics:
                    print(format_diagnostic(diag))

        except EOFError:
            print("\nGoodbye!")
            break
        except KeyboardInterrupt:
            if draft:
                draft = ""
                draft_status = None
                draft_program = None
                print("\nDraft cleared.")
                continue
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Unexpected internal error: {e}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        prog="rune",
        description="RUNE (Runtime Unicode Numeric Evaluation)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    rune program.rune              # Run a RUNE file
    rune program.rune --verbose    # Show execution details
    rune program.rune --show-ast   # Show Abstract Syntax Tree
    rune program.rune --unbounded  # Trusted run without budgets
    rune --repl                    # Interactive REPL mode
        """
    )
    
    parser.add_argument(
        'file',
        nargs='?',
        help='RUNE source file to execute'
    )
    parser.add_argument(
        '--repl',
        action='store_true',
        help='Start interactive REPL mode'
    )
    parser.add_argument(
        '--show-tokens',
        action='store_true',
        help='Display token stream'
    )
    parser.add_argument(
        '--show-ast',
        action='store_true',
        help='Display Abstract Syntax Tree'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show verbose execution details'
    )
    parser.add_argument(
        '--unbounded',
        action='store_true',
        help=(
            'Disable interpreter budgets for this trusted local run; '
            'programs may run forever or exhaust host resources'
        ),
    )
    
    args = parser.parse_args()
    
    limits = ExecutionLimits.unbounded() if args.unbounded else None

    # Handle REPL mode
    if args.repl:
        repl(limits=limits)
        return 0
    
    # Must provide a file if not in REPL mode
    if not args.file:
        parser.print_help()
        return 1
    
    # Run the file
    return run_file(
        args.file,
        show_tokens=args.show_tokens,
        show_ast=args.show_ast,
        verbose=args.verbose,
        limits=limits,
    )


if __name__ == "__main__":
    sys.exit(main())
