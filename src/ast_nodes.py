class SpannedNode:
    """Shared source-range behavior for AST nodes."""
    def _set_span(self, span=None):
        self.span = span


class NumberNode(SpannedNode):
    """Represents a number literal: 42"""
    def __init__(self, value, span=None):
        self.value = value
        self._set_span(span)

    def __repr__(self):
        return f"Num({self.value})"


class StringNode(SpannedNode):
    """Represents a string literal: "cat" """
    def __init__(self, value, span=None):
        self.value = value
        self._set_span(span)

    def __repr__(self):
        return f"Str({self.value})"


class VariableNode(SpannedNode):
    """Represents a variable lookup: score"""
    def __init__(self, name, span=None):
        self.name = name
        self._set_span(span)

    def __repr__(self):
        return f"Variable({self.name})"


class AssignmentNode(SpannedNode):
    """Represents assignment of an evaluated numeric value: score = 42"""
    def __init__(self, name, value, span=None):
        self.name = name
        self.value = value
        self._set_span(span)

    def __repr__(self):
        return f"Assign({self.name} = {self.value})"


class BinaryOpNode(SpannedNode):
    """Represents a binary operation: left op right"""
    def __init__(self, left, op, right, span=None):
        self.left = left
        self.op = op
        self.right = right
        self._set_span(span)

    def __repr__(self):
        return f"BinOp({self.left} {self.op.value} {self.right})"


class ComparisonNode(SpannedNode):
    """Represents a comparison operation: left op right"""
    def __init__(self, left, op, right, span=None):
        self.left = left
        self.op = op
        self.right = right
        self._set_span(span)

    def __repr__(self):
        return f"Compare({self.left} {self.op.value} {self.right})"


class ChaosPragmaNode(SpannedNode):
    """Represents @chaos pragma directive"""
    def __init__(self, threshold, span=None):
        self.threshold = threshold
        self._set_span(span)

    def __repr__(self):
        return f"ChaosPragma({self.threshold})"


class IfNode(SpannedNode):
    """Represents an if/elif/else conditional."""
    def __init__(
        self,
        condition,
        then_block,
        elif_clauses=None,
        else_block=None,
        span=None,
    ):
        self.condition = condition
        self.then_block = then_block
        self.elif_clauses = elif_clauses or []
        self.else_block = else_block
        self._set_span(span)

    def __repr__(self):
        return (
            f"If({self.condition}, then={self.then_block}, "
            f"elif={self.elif_clauses}, else={self.else_block})"
        )


class ProgramNode(SpannedNode):
    """Represents a program with multiple statements"""
    def __init__(self, statements, span=None):
        self.statements = statements
        self._set_span(span)

    def __repr__(self):
        return f"Program({self.statements})"
