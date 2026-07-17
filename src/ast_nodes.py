class NumberNode:
    """Represents a number literal: 42"""
    def __init__(self, value, position=None):
        self.value = value
        self.position = position

    def __repr__(self):
        return f"Num({self.value})"


class StringNode:
    """Represents a string literal: "cat" """
    def __init__(self, value, position=None):
        self.value = value
        self.position = position

    def __repr__(self):
        return f"Str({self.value})"


class BinaryOpNode:
    """Represents a binary operation: left op right"""
    def __init__(self, left, op, right, position=None):
        self.left = left
        self.op = op
        self.right = right
        self.position = position

    def __repr__(self):
        return f"BinOp({self.left} {self.op.value} {self.right})"


class ComparisonNode:
    """Represents a comparison operation: left op right"""
    def __init__(self, left, op, right, position=None):
        self.left = left
        self.op = op
        self.right = right
        self.position = position

    def __repr__(self):
        return f"Compare({self.left} {self.op.value} {self.right})"


class ChaosPragmaNode:
    """Represents @chaos pragma directive"""
    def __init__(self, threshold, position=None):
        self.threshold = threshold
        self.position = position

    def __repr__(self):
        return f"ChaosPragma({self.threshold})"


class IfNode:
    """Represents an if/elif/else conditional."""
    def __init__(self, condition, then_block, elif_clauses=None, else_block=None, position=None):
        self.condition = condition
        self.then_block = then_block
        self.elif_clauses = elif_clauses or []
        self.else_block = else_block
        self.position = position

    def __repr__(self):
        return (
            f"If({self.condition}, then={self.then_block}, "
            f"elif={self.elif_clauses}, else={self.else_block})"
        )


class ProgramNode:
    """Represents a program with multiple statements"""
    def __init__(self, statements, position=None):
        self.statements = statements
        self.position = position

    def __repr__(self):
        return f"Program({self.statements})"
