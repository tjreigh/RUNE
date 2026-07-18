#!/usr/bin/env python3
"""
RUNE (Runtime Unicode Numeric Evaluation)
A language where everything collapses to ASCII sums

Usage:
    python3.12 rune.py <file.rune>               # Run a RUNE file
    python3.12 rune.py <file.rune> --verbose     # Show execution details
    python3.12 rune.py <file.rune> --show-ast    # Show Abstract Syntax Tree
    python3.12 rune.py <file.rune> --show-tokens # Show token stream
    python3.12 rune.py --repl                    # Interactive REPL mode
"""

import sys
import argparse
from pathlib import Path

from runtime import RuntimeState, compile_source, execute, evaluate
from diagnostics import RuneError, Diagnostic, DiagnosticKind

_ERROR_LABELS = {
    DiagnosticKind.LEX: "Lex error",
    DiagnosticKind.PARSE: "Parse error",
    DiagnosticKind.RUNTIME: "Runtime error",
    DiagnosticKind.INTERNAL: "Internal error",
    DiagnosticKind.LIMIT: "Execution limit",
}


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
    return f"[{event.kind.upper()}] {event.data}"


def run_file(filepath, show_tokens=False, show_ast=False, verbose=False):
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
    return run_code(code, filepath, show_tokens, show_ast, verbose)


def run_code(code, source_name="<input>", show_tokens=False, show_ast=False, verbose=False):
    """Execute RUNE code string"""
    if not code.strip():
        return 0
    
    try:
        program = compile_source(code)
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
        result = execute(program)
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


def repl():
    """Interactive REPL mode"""
    print("RUNE Interactive REPL")
    print("Type expressions to evaluate them. Ctrl+C or Ctrl+D to exit.")
    print("=" * 60)
    
    state = RuntimeState()

    while True:
        try:
            code = input("rune> ")

            if not code.strip():
                continue

            result = evaluate(code, state)

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
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Unexpected internal error: {e}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="RUNE (Runtime Unicode Numeric Evaluation)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python3.12 rune.py program.rune              # Run a RUNE file
    python3.12 rune.py program.rune --verbose    # Show execution details
    python3.12 rune.py program.rune --show-ast   # Show Abstract Syntax Tree
    python3.12 rune.py --repl                    # Interactive REPL mode
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
    
    args = parser.parse_args()
    
    # Handle REPL mode
    if args.repl:
        repl()
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
        verbose=args.verbose
    )


if __name__ == "__main__":
    sys.exit(main())
