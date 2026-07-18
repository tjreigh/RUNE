from tokens import TokenType
from ast_nodes import (
    BinaryOpNode,
    NumberNode,
    StringNode,
    ComparisonNode,
    ChaosPragmaNode,
    VariableNode,
    AssignmentNode,
    IfNode,
    ProgramNode,
)
from diagnostics import RuneParseError
from spans import SourceSpan

class Parser:
    """
    Parses tokens into an Abstract Syntax Tree (AST)
    Grammar:
        program   : statement* EOF
        statement : pragma | if_stmt | assignment | expr
        assignment: IDENTIFIER ASSIGN expr
        pragma    : PRAGMA CHAOS NUMBER
        if_stmt   : IF LPAREN expr RPAREN statement*
                    (ELIF LPAREN expr RPAREN statement*)*
                    (ELSE statement*)? END
        expr      : comparison
        comparison: arith_expr ((LT | GT | LTE | GTE | EQ | NEQ) arith_expr)*
        arith_expr: term ((PLUS | MINUS) term)*
        term      : factor (MULT factor)*
        factor    : NUMBER | STRING | IDENTIFIER
    """

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def current_token(self):
        """Get the current token without consuming it"""
        return self.tokens[self.pos]

    def peek_token(self):
        """Get the token after the current token without consuming it."""
        return self.tokens[min(self.pos + 1, len(self.tokens) - 1)]

    def eat(self, token_type):
        """Consume a token of expected type, or raise error"""
        if self.current_token().type == token_type:
            self.pos += 1
        else:
            raise RuneParseError(
                f"Expected {token_type.value}, got {self.current_token().type.value}",
                self.current_token().span,
            )

    def parse(self):
        """Entry point - parse the token stream"""
        return self.program()

    def skip_newlines(self):
        """Skip any consecutive newline tokens"""
        while self.current_token().type == TokenType.NEWLINE:
            self.eat(TokenType.NEWLINE)

    def program(self):
        """
        Parse program: statement* EOF
        """
        statements = self.block({TokenType.EOF})
        eof_token = self.current_token()
        self.eat(TokenType.EOF)

        # If we have multiple statements, wrap in ProgramNode
        if len(statements) > 1:
            return ProgramNode(
                statements,
                span=SourceSpan.covering(statements[0].span, statements[-1].span),
            )
        elif len(statements) == 1:
            return statements[0]
        else:
            # Empty program
            raise RuneParseError("Empty program", eof_token.span)

    def block(self, terminators):
        """Parse statements until one of the supplied terminators is reached."""
        statements = []
        self.skip_newlines()

        while self.current_token().type not in terminators:
            if self.current_token().type == TokenType.EOF:
                expected = ", ".join(sorted(t.value for t in terminators))
                raise RuneParseError(
                    f"Unexpected end of input; expected one of: {expected}",
                    self.current_token().span,
                )

            statements.append(self.statement())
            self.skip_newlines()

        return statements

    def statement(self):
        """Parse a pragma, conditional, or expression statement."""
        if self.current_token().type == TokenType.PRAGMA:
            return self.pragma()
        elif self.current_token().type == TokenType.IF:
            return self.if_stmt()
        elif (
            self.current_token().type == TokenType.IDENTIFIER
            and self.peek_token().type == TokenType.ASSIGN
        ):
            return self.assignment()
        return self.expr()

    def assignment(self):
        """Parse assignment: IDENTIFIER ASSIGN expr."""
        name_token = self.current_token()
        self.eat(TokenType.IDENTIFIER)
        self.eat(TokenType.ASSIGN)
        value = self.expr()
        return AssignmentNode(
            name_token.value,
            value,
            span=SourceSpan(name_token.span.start, value.span.end),
        )

    def pragma(self):
        """Parse pragma: PRAGMA CHAOS NUMBER"""
        start = self.current_token().span.start
        self.eat(TokenType.PRAGMA)
        self.eat(TokenType.CHAOS)
        threshold_token = self.current_token()
        self.eat(TokenType.NUMBER)
        return ChaosPragmaNode(
            threshold_token.value,
            span=SourceSpan(start, threshold_token.span.end),
        )

    def if_stmt(self):
        """Parse an if/elif/else/end conditional."""
        start = self.current_token().span.start
        self.eat(TokenType.IF)
        self.eat(TokenType.LPAREN)
        condition = self.expr()
        self.eat(TokenType.RPAREN)

        branch_terminators = {TokenType.ELIF, TokenType.ELSE, TokenType.END}
        then_block = self.block(branch_terminators)
        elif_clauses = []

        while self.current_token().type == TokenType.ELIF:
            self.eat(TokenType.ELIF)
            self.eat(TokenType.LPAREN)
            elif_condition = self.expr()
            self.eat(TokenType.RPAREN)
            elif_block = self.block(branch_terminators)
            elif_clauses.append((elif_condition, elif_block))

        else_block = None
        if self.current_token().type == TokenType.ELSE:
            self.eat(TokenType.ELSE)
            else_block = self.block({TokenType.END})

        end_token = self.current_token()
        self.eat(TokenType.END)
        return IfNode(
            condition,
            then_block,
            elif_clauses,
            else_block,
            span=SourceSpan(start, end_token.span.end),
        )

    def expr(self):
        """
        Parse expression: comparison
        Entry point for expressions
        """
        return self.comparison()

    def comparison(self):
        """
        Parse comparison: arith_expr ((LT | GT | LTE | GTE | EQ | NEQ) arith_expr)*
        This handles comparison operators (lowest precedence in expressions)
        """
        node = self.arith_expr()

        comparison_ops = [TokenType.LT, TokenType.GT, TokenType.LTE,
                         TokenType.GTE, TokenType.EQ, TokenType.NEQ]

        while self.current_token().type in comparison_ops:
            op = self.current_token()
            self.eat(op.type)
            right = self.arith_expr()
            node = ComparisonNode(
                node,
                op,
                right,
                span=SourceSpan.covering(node.span, right.span),
            )

        return node

    def arith_expr(self):
        """
        Parse arith_expr: term ((PLUS | MINUS) term)*
        This handles addition and subtraction
        """
        node = self.term()

        while self.current_token().type in [TokenType.PLUS, TokenType.MINUS]:
            op = self.current_token()
            self.eat(op.type)
            right = self.term()
            node = BinaryOpNode(
                node,
                op,
                right,
                span=SourceSpan.covering(node.span, right.span),
            )

        return node

    def term(self):
        """
        Parse term: factor (MULT factor)*
        This handles multiplication (higher precedence than +/-)
        """
        node = self.factor()

        while self.current_token().type == TokenType.MULT:
            op = self.current_token()
            self.eat(TokenType.MULT)
            right = self.factor()
            node = BinaryOpNode(
                node,
                op,
                right,
                span=SourceSpan.covering(node.span, right.span),
            )

        return node

    def factor(self):
        """
        Parse factor: NUMBER | STRING
        These are the "atomic" values in expressions
        """
        token = self.current_token()

        if token.type == TokenType.NUMBER:
            self.eat(TokenType.NUMBER)
            return NumberNode(token.value, span=token.span)
        elif token.type == TokenType.STRING:
            self.eat(TokenType.STRING)
            return StringNode(token.value, span=token.span)
        elif token.type == TokenType.IDENTIFIER:
            self.eat(TokenType.IDENTIFIER)
            return VariableNode(token.value, span=token.span)
        else:
            raise RuneParseError(f"Unexpected token: {token.type.value}", token.span)
