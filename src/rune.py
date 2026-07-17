#!/usr/bin/env python3
"""
RUNE (Runtime Unicode Numeric Evaluation)
A language where everything collapses to ASCII sums

Usage:
    python rune.py <file.rune>              # Run a RUNE file
    python rune.py <file.rune> --verbose    # Show execution details
    python rune.py <file.rune> --show-ast   # Show Abstract Syntax Tree
    python rune.py <file.rune> --show-tokens # Show token stream
    python rune.py --repl                   # Interactive REPL mode
"""

import sys
import argparse
from pathlib import Path

from lexer import Lexer
from parser import Parser
from interpreter import Interpreter
from diagnostics import RuneError, DiagnosticKind

_ERROR_LABELS = {
    DiagnosticKind.LEX: "Lex error",
    DiagnosticKind.PARSE: "Parse error",
    DiagnosticKind.RUNTIME: "Runtime error",
    DiagnosticKind.INTERNAL: "Internal error",
}


def format_error(err: RuneError) -> str:
    """Render a structured RUNE diagnostic for terminal output."""
    return f"{_ERROR_LABELS[err.diagnostic.kind]}: {err.diagnostic.format()}"


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
        # Lex
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        
        if show_tokens:
            print(f"\n{'='*60}")
            print(f"TOKENS from {source_name}")
            print(f"{'='*60}")
            for i, token in enumerate(tokens[:-1]):  # Skip EOF
                print(f"  {i}: {token}")
            print()
        
        # Parse
        parser = Parser(tokens)
        ast = parser.parse()
        
        if show_ast:
            print(f"\n{'='*60}")
            print(f"AST from {source_name}")
            print(f"{'='*60}")
            print(f"  {ast}")
            print()
        
        # Interpret
        interpreter = Interpreter()
        interpreter.verbose = verbose
        
        if verbose:
            print(f"\n{'='*60}")
            print(f"EXECUTION of {source_name}")
            print(f"{'='*60}")
        
        result = interpreter.interpret(ast)

        # Output result(s)
        if isinstance(result, list):
            # Multiple results from multi-line program
            for r in result:
                print(r)
        else:
            # Single result
            print(result)

        return 0

    except RuneError as e:
        print(format_error(e), file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected internal error: {e}", file=sys.stderr)
        return 1


def repl():
    """Interactive REPL mode"""
    print("RUNE Interactive REPL")
    print("Type expressions to evaluate them. Ctrl+C or Ctrl+D to exit.")
    print("=" * 60)
    
    interpreter = Interpreter()
    
    while True:
        try:
            # Get input
            code = input("rune> ")
            
            if not code.strip():
                continue
            
            # Lex
            lexer = Lexer(code)
            tokens = lexer.tokenize()
            
            # Parse
            parser = Parser(tokens)
            ast = parser.parse()
            
            # Interpret
            result = interpreter.interpret(ast)

            # Output
            if isinstance(result, list):
                # Multiple results
                for r in result:
                    print(f"=> {r}")
            else:
                # Single result
                print(f"=> {result}")
            
        except EOFError:
            print("\nGoodbye!")
            break
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except RuneError as e:
            print(format_error(e))
        except Exception as e:
            print(f"Unexpected internal error: {e}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="RUNE (Runtime Unicode Numeric Evaluation)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python rune.py program.rune              # Run a RUNE file
    python rune.py program.rune --verbose    # Show execution details
    python rune.py program.rune --show-ast   # Show Abstract Syntax Tree
    python rune.py --repl                    # Interactive REPL mode
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
