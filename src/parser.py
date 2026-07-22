from tokens import TokenType
from ast_nodes import (
    BinaryOpNode,
    NumberNode,
    StringNode,
    ComparisonNode,
    LogicalOpNode,
    LogicalNotNode,
    ChaosPragmaNode,
    VariableNode,
    AssignmentNode,
    GroupNode,
    UnaryOpNode,
    IfNode,
    ProgramNode,
)
from diagnostics import RuneParseError
from spans import SourceSpan

MAX_EXPRESSION_NESTING = 100

_COMPARISON_OPERATORS = frozenset({
    TokenType.LT,
    TokenType.GT,
    TokenType.LTE,
    TokenType.GTE,
    TokenType.EQ,
    TokenType.NEQ,
})

# Conventional binary operators are left-associative. Larger numbers bind
# more tightly; unary and power are parsed separately above these levels.
_BINARY_PRECEDENCE = {
    **{operator: 1 for operator in _COMPARISON_OPERATORS},
    TokenType.BIT_OR: 2,
    TokenType.BIT_XOR: 3,
    TokenType.BIT_AND: 4,
    TokenType.SHIFT_LEFT: 5,
    TokenType.SHIFT_RIGHT: 5,
    TokenType.PLUS: 6,
    TokenType.MINUS: 6,
    TokenType.MULT: 7,
    TokenType.DIV: 7,
    TokenType.MOD: 7,
}


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
        expr      : logical_or
        logical_or: logical_and (OR logical_and)*
        logical_and: logical_not (AND logical_not)*
        logical_not: NOT logical_not | comparison
        comparison: bitwise_or ((LT | GT | LTE | GTE | EQ | NEQ) bitwise_or)*
        bitwise_or: bitwise_xor (BIT_OR bitwise_xor)*
        bitwise_xor: bitwise_and (BIT_XOR bitwise_and)*
        bitwise_and: shift (BIT_AND shift)*
        shift     : arith_expr ((SHIFT_LEFT | SHIFT_RIGHT) arith_expr)*
        arith_expr: term ((PLUS | MINUS) term)*
        term      : unary ((MULT | DIV | MOD) unary)*
        unary     : (MINUS | BIT_NOT) unary | power
        power     : primary (POWER unary)?
        primary   : NUMBER | STRING | IDENTIFIER | LPAREN expr RPAREN
    """

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self._expression_nesting = 0

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

    def parse_nested(self, parse_fn, token):
        """Run one recursive expression parse within a safe depth bound."""
        self._expression_nesting += 1
        try:
            if self._expression_nesting > MAX_EXPRESSION_NESTING:
                raise RuneParseError(
                    f"Expression nesting exceeds the {MAX_EXPRESSION_NESTING}-level limit",
                    token.span,
                )
            return parse_fn()
        finally:
            self._expression_nesting -= 1

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
        """Parse a complete expression, including short-circuiting logic."""
        return self.logical_or()

    def logical_or(self):
        """Parse left-associative logical OR expressions."""
        node = self.logical_and()
        while self.current_token().type == TokenType.OR:
            op = self.current_token()
            self.eat(TokenType.OR)
            right = self.logical_and()
            node = LogicalOpNode(
                node,
                op,
                right,
                span=SourceSpan.covering(node.span, right.span),
            )
        return node

    def logical_and(self):
        """Parse left-associative logical AND expressions."""
        node = self.logical_not()
        while self.current_token().type == TokenType.AND:
            op = self.current_token()
            self.eat(TokenType.AND)
            right = self.logical_not()
            node = LogicalOpNode(
                node,
                op,
                right,
                span=SourceSpan.covering(node.span, right.span),
            )
        return node

    def logical_not(self):
        """Parse right-nested logical negation below comparison precedence."""
        token = self.current_token()
        if token.type == TokenType.NOT:
            self.eat(TokenType.NOT)
            operand = self.parse_nested(self.logical_not, token)
            return LogicalNotNode(
                token,
                operand,
                span=SourceSpan(token.span.start, operand.span.end),
            )
        return self.binary_expression()

    def binary_expression(self, minimum_precedence=1):
        """Parse left-associative binary operators without one stack frame
        per precedence level, preserving the 100-level nesting guarantee."""
        node = self.unary()

        while True:
            op = self.current_token()
            precedence = _BINARY_PRECEDENCE.get(op.type)
            if precedence is None or precedence < minimum_precedence:
                break
            self.eat(op.type)
            right = self.binary_expression(precedence + 1)
            node_type = (
                ComparisonNode
                if op.type in _COMPARISON_OPERATORS
                else BinaryOpNode
            )
            node = node_type(
                node,
                op,
                right,
                span=SourceSpan.covering(node.span, right.span),
            )
        return node

    def unary(self):
        """Parse a right-nested prefix unary expression."""
        token = self.current_token()
        if token.type in [TokenType.MINUS, TokenType.BIT_NOT]:
            self.eat(token.type)
            operand = self.parse_nested(self.unary, token)
            return UnaryOpNode(
                token,
                operand,
                span=SourceSpan(token.span.start, operand.span.end),
            )
        return self.power()

    def power(self):
        """Parse right-associative power, which binds tighter than unary."""
        node = self.primary()
        if self.current_token().type == TokenType.POWER:
            op = self.current_token()
            self.eat(TokenType.POWER)
            right = self.parse_nested(self.unary, op)
            node = BinaryOpNode(
                node,
                op,
                right,
                span=SourceSpan.covering(node.span, right.span),
            )
        return node

    def primary(self):
        """
        Parse primary: NUMBER | STRING | IDENTIFIER | LPAREN expr RPAREN
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
        elif token.type == TokenType.LPAREN:
            self.eat(TokenType.LPAREN)
            expression = self.parse_nested(self.expr, token)
            closing = self.current_token()
            self.eat(TokenType.RPAREN)
            return GroupNode(
                expression,
                span=SourceSpan(token.span.start, closing.span.end),
            )
        else:
            raise RuneParseError(f"Unexpected token: {token.type.value}", token.span)
