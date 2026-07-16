from tokens import TokenType
from ast_nodes import BinaryOpNode, NumberNode, StringNode, ComparisonNode, ChaosPragmaNode, ProgramNode

class Parser:
    """
    Parses tokens into an Abstract Syntax Tree (AST)
    Grammar:
        program   : line* EOF
        line      : (pragma | expr) NEWLINE*
        pragma    : PRAGMA CHAOS NUMBER
        expr      : comparison
        comparison: arith_expr ((LT | GT | LTE | GTE | EQ | NEQ) arith_expr)*
        arith_expr: term ((PLUS | MINUS) term)*
        term      : factor (MULT factor)*
        factor    : NUMBER | STRING
    """

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def current_token(self):
        """Get the current token without consuming it"""
        return self.tokens[self.pos]

    def eat(self, token_type):
        """Consume a token of expected type, or raise error"""
        if self.current_token().type == token_type:
            self.pos += 1
        else:
            raise Exception(f"Expected {token_type}, got {self.current_token().type}")

    def parse(self):
        """Entry point - parse the token stream"""
        return self.program()

    def skip_newlines(self):
        """Skip any consecutive newline tokens"""
        while self.current_token().type == TokenType.NEWLINE:
            self.eat(TokenType.NEWLINE)

    def program(self):
        """
        Parse program: line* EOF
        Parse multiple lines (pragmas or expressions) separated by newlines
        """
        statements = []

        # Skip leading newlines
        self.skip_newlines()

        # Parse lines until EOF
        while self.current_token().type != TokenType.EOF:
            # Parse a line (pragma or expression)
            if self.current_token().type == TokenType.PRAGMA:
                statements.append(self.pragma())
            else:
                statements.append(self.expr())

            # Skip trailing newlines after this line
            self.skip_newlines()

        # If we have multiple statements, wrap in ProgramNode
        if len(statements) > 1:
            return ProgramNode(statements)
        elif len(statements) == 1:
            return statements[0]
        else:
            # Empty program
            raise Exception("Empty program")

    def statement(self):
        """Parse a statement (currently only pragmas)"""
        if self.current_token().type == TokenType.PRAGMA:
            return self.pragma()
        else:
            raise Exception(f"Unexpected token in statement: {self.current_token().type}")

    def pragma(self):
        """Parse pragma: PRAGMA CHAOS NUMBER"""
        self.eat(TokenType.PRAGMA)
        self.eat(TokenType.CHAOS)
        threshold_token = self.current_token()
        self.eat(TokenType.NUMBER)
        return ChaosPragmaNode(threshold_token.value)
    
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
            node = ComparisonNode(node, op, self.arith_expr())

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
            node = BinaryOpNode(node, op, self.term())

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
            node = BinaryOpNode(node, op, self.factor())
        
        return node
    
    def factor(self):
        """
        Parse factor: NUMBER | STRING
        These are the "atomic" values in expressions
        """
        token = self.current_token()
        
        if token.type == TokenType.NUMBER:
            self.eat(TokenType.NUMBER)
            return NumberNode(token.value)
        elif token.type == TokenType.STRING:
            self.eat(TokenType.STRING)
            return StringNode(token.value)
        else:
            raise Exception(f"Unexpected token: {token.type}")