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
    WhileNode,
    ForNode,
    BreakNode,
    ContinueNode,
    FunctionDefinitionNode,
    FunctionCallNode,
    ReturnNode,
    ProgramNode,
)
from diagnostics import RuneParseError
from spans import SourceSpan

MAX_EXPRESSION_NESTING = 100
MAX_BLOCK_NESTING = 100

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
        statement : pragma | if_stmt | while_stmt | for_stmt | function_stmt |
                    return_stmt | break_stmt | continue_stmt | assignment | expr
        assignment: IDENTIFIER ASSIGN expr
        pragma    : PRAGMA CHAOS NUMBER
        if_stmt   : IF LPAREN expr RPAREN statement*
                    (ELIF LPAREN expr RPAREN statement*)*
                    (ELSE statement*)? END IF
        while_stmt: WHILE LPAREN expr RPAREN statement* END WHILE
        for_stmt  : FOR IDENTIFIER FROM expr TO expr (STEP expr)?
                    statement* END FOR
        break_stmt: BREAK
        continue_stmt: CONTINUE
        function_stmt: FUNCTION IDENTIFIER LPAREN parameters? RPAREN
                       statement* END FUNCTION
        parameters: IDENTIFIER (COMMA IDENTIFIER)*
        return_stmt: RETURN expr
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
        primary   : NUMBER | STRING | call | IDENTIFIER | LPAREN expr RPAREN
        call      : IDENTIFIER LPAREN arguments? RPAREN
        arguments : expr (COMMA expr)*
    """

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self._expression_nesting = 0
        self._block_nesting = 0
        self._loop_depth = 0
        self._function_depth = 0
        self._function_names = set()

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

    def parse_nested_block(self, terminators, opener):
        """Parse one nested statement block within a fixed depth bound."""
        self._block_nesting += 1
        try:
            if self._block_nesting > MAX_BLOCK_NESTING:
                raise RuneParseError(
                    f"Block nesting exceeds the {MAX_BLOCK_NESTING}-level limit",
                    opener.span,
                )
            return self.block(terminators)
        finally:
            self._block_nesting -= 1

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

    def block_end(self, block_type):
        """Consume ``end <block type>`` and return the closing label token."""
        self.eat(TokenType.END)
        if self.current_token().type != block_type:
            label = block_type.value.lower()
            raise RuneParseError(
                f"Expected '{label}' after 'end'",
                self.current_token().span,
            )
        closing = self.current_token()
        self.eat(block_type)
        return closing

    def statement(self):
        """Parse a pragma, conditional, or expression statement."""
        if self.current_token().type == TokenType.PRAGMA:
            return self.pragma()
        elif self.current_token().type == TokenType.IF:
            return self.if_stmt()
        elif self.current_token().type == TokenType.WHILE:
            return self.while_stmt()
        elif self.current_token().type == TokenType.FOR:
            return self.for_stmt()
        elif self.current_token().type == TokenType.FUNCTION:
            return self.function_stmt()
        elif self.current_token().type == TokenType.RETURN:
            return self.return_stmt()
        elif self.current_token().type == TokenType.BREAK:
            return self.break_stmt()
        elif self.current_token().type == TokenType.CONTINUE:
            return self.continue_stmt()
        elif (
            self.current_token().type == TokenType.IDENTIFIER
            and self.peek_token().type == TokenType.ASSIGN
        ):
            return self.assignment()
        return self.expr()

    def function_stmt(self):
        """Parse a top-level function declaration with a lexical body."""
        function_token = self.current_token()
        if self._block_nesting != 0 or self._function_depth != 0:
            raise RuneParseError(
                "Function declarations are only valid at the top level",
                function_token.span,
            )

        start = function_token.span.start
        self.eat(TokenType.FUNCTION)
        name_token = self.current_token()
        self.eat(TokenType.IDENTIFIER)
        if name_token.value in self._function_names:
            raise RuneParseError(
                f"Function '{name_token.value}' is already defined",
                name_token.span,
            )
        self._function_names.add(name_token.value)

        self.eat(TokenType.LPAREN)
        parameters = []
        parameter_names = set()
        if self.current_token().type != TokenType.RPAREN:
            while True:
                parameter = self.current_token()
                self.eat(TokenType.IDENTIFIER)
                if parameter.value in parameter_names:
                    raise RuneParseError(
                        f"Duplicate parameter '{parameter.value}'",
                        parameter.span,
                    )
                parameter_names.add(parameter.value)
                parameters.append(parameter.value)
                if self.current_token().type != TokenType.COMMA:
                    break
                self.eat(TokenType.COMMA)
        self.eat(TokenType.RPAREN)

        previous_loop_depth = self._loop_depth
        self._loop_depth = 0
        self._function_depth += 1
        try:
            body = self.parse_nested_block({TokenType.END}, function_token)
        finally:
            self._function_depth -= 1
            self._loop_depth = previous_loop_depth

        end_label = self.block_end(TokenType.FUNCTION)
        return FunctionDefinitionNode(
            name_token.value,
            parameters,
            body,
            name_span=name_token.span,
            span=SourceSpan(start, end_label.span.end),
        )

    def return_stmt(self):
        """Parse a value-returning statement only inside a function body."""
        token = self.current_token()
        if self._function_depth == 0:
            raise RuneParseError(
                "'return' is only valid inside a function",
                token.span,
            )
        self.eat(TokenType.RETURN)
        value = self.expr()
        return ReturnNode(
            value,
            span=SourceSpan(token.span.start, value.span.end),
        )

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
        """Parse an if/elif/else/end if conditional."""
        if_token = self.current_token()
        start = if_token.span.start
        self.eat(TokenType.IF)
        self.eat(TokenType.LPAREN)
        condition = self.expr()
        self.eat(TokenType.RPAREN)

        branch_terminators = {TokenType.ELIF, TokenType.ELSE, TokenType.END}
        then_block = self.parse_nested_block(branch_terminators, if_token)
        elif_clauses = []

        while self.current_token().type == TokenType.ELIF:
            elif_token = self.current_token()
            self.eat(TokenType.ELIF)
            self.eat(TokenType.LPAREN)
            elif_condition = self.expr()
            self.eat(TokenType.RPAREN)
            elif_block = self.parse_nested_block(branch_terminators, elif_token)
            elif_clauses.append((elif_condition, elif_block))

        else_block = None
        if self.current_token().type == TokenType.ELSE:
            else_token = self.current_token()
            self.eat(TokenType.ELSE)
            else_block = self.parse_nested_block({TokenType.END}, else_token)

        end_label = self.block_end(TokenType.IF)
        return IfNode(
            condition,
            then_block,
            elif_clauses,
            else_block,
            span=SourceSpan(start, end_label.span.end),
        )

    def while_stmt(self):
        """Parse a while/end while loop."""
        while_token = self.current_token()
        start = while_token.span.start
        self.eat(TokenType.WHILE)
        self.eat(TokenType.LPAREN)
        condition = self.expr()
        self.eat(TokenType.RPAREN)

        self._loop_depth += 1
        try:
            body = self.parse_nested_block({TokenType.END}, while_token)
        finally:
            self._loop_depth -= 1

        end_label = self.block_end(TokenType.WHILE)
        return WhileNode(
            condition,
            body,
            span=SourceSpan(start, end_label.span.end),
        )

    def for_stmt(self):
        """Parse an inclusive counted for/end for loop."""
        for_token = self.current_token()
        start = for_token.span.start
        self.eat(TokenType.FOR)
        counter_token = self.current_token()
        self.eat(TokenType.IDENTIFIER)
        self.eat(TokenType.FROM)
        start_value = self.expr()
        self.eat(TokenType.TO)
        stop_value = self.expr()

        step_value = None
        if self.current_token().type == TokenType.STEP:
            self.eat(TokenType.STEP)
            step_value = self.expr()

        self._loop_depth += 1
        try:
            body = self.parse_nested_block({TokenType.END}, for_token)
        finally:
            self._loop_depth -= 1

        end_label = self.block_end(TokenType.FOR)
        return ForNode(
            counter_token.value,
            start_value,
            stop_value,
            body,
            step=step_value,
            counter_span=counter_token.span,
            span=SourceSpan(start, end_label.span.end),
        )

    def break_stmt(self):
        """Parse break only within a lexically enclosing loop."""
        token = self.current_token()
        if self._loop_depth == 0:
            raise RuneParseError("'break' is only valid inside a loop", token.span)
        self.eat(TokenType.BREAK)
        return BreakNode(span=token.span)

    def continue_stmt(self):
        """Parse continue only within a lexically enclosing loop."""
        token = self.current_token()
        if self._loop_depth == 0:
            raise RuneParseError(
                "'continue' is only valid inside a loop", token.span
            )
        self.eat(TokenType.CONTINUE)
        return ContinueNode(span=token.span)

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
            if self.current_token().type == TokenType.LPAREN:
                self.eat(TokenType.LPAREN)
                arguments = []
                if self.current_token().type != TokenType.RPAREN:
                    while True:
                        arguments.append(self.parse_nested(self.expr, token))
                        if self.current_token().type != TokenType.COMMA:
                            break
                        self.eat(TokenType.COMMA)
                closing = self.current_token()
                self.eat(TokenType.RPAREN)
                return FunctionCallNode(
                    token.value,
                    arguments,
                    name_span=token.span,
                    span=SourceSpan(token.span.start, closing.span.end),
                )
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
