class NumberNode:
    """Represents a number literal: 42"""
    def __init__(self, value):
        self.value = value
    
    def __repr__(self):
        return f"Num({self.value})"


class StringNode:
    """Represents a string literal: "cat" """
    def __init__(self, value):
        self.value = value
    
    def __repr__(self):
        return f"Str({self.value})"


class BinaryOpNode:
    """Represents a binary operation: left op right"""
    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right

    def __repr__(self):
        return f"BinOp({self.left} {self.op.value} {self.right})"


class ComparisonNode:
    """Represents a comparison operation: left op right"""
    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right

    def __repr__(self):
        return f"Compare({self.left} {self.op.value} {self.right})"


class ChaosPragmaNode:
    """Represents @chaos pragma directive"""
    def __init__(self, threshold):
        self.threshold = threshold

    def __repr__(self):
        return f"ChaosPragma({self.threshold})"


class IfNode:
    """Represents an if/elif/else conditional."""
    def __init__(self, condition, then_block, elif_clauses=None, else_block=None):
        self.condition = condition
        self.then_block = then_block
        self.elif_clauses = elif_clauses or []
        self.else_block = else_block

    def __repr__(self):
        return (
            f"If({self.condition}, then={self.then_block}, "
            f"elif={self.elif_clauses}, else={self.else_block})"
        )


class ProgramNode:
    """Represents a program with multiple statements"""
    def __init__(self, statements):
        self.statements = statements

    def __repr__(self):
        return f"Program({self.statements})"
