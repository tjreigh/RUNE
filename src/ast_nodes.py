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


class GroupNode(SpannedNode):
    """Represents an explicitly parenthesized expression: (2 + 3)"""
    def __init__(self, expression, span=None):
        self.expression = expression
        self._set_span(span)

    def __repr__(self):
        return f"Group({self.expression})"


class UnaryOpNode(SpannedNode):
    """Represents a prefix unary operation: -value or ~value"""
    def __init__(self, op, operand, span=None):
        self.op = op
        self.operand = operand
        self._set_span(span)

    def __repr__(self):
        return f"UnaryOp({self.op.value} {self.operand})"


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


class LogicalOpNode(SpannedNode):
    """Represents a short-circuiting logical operation: left and/or right."""
    def __init__(self, left, op, right, span=None):
        self.left = left
        self.op = op
        self.right = right
        self._set_span(span)

    def __repr__(self):
        return f"LogicalOp({self.left} {self.op.value} {self.right})"


class LogicalNotNode(SpannedNode):
    """Represents chaos-aware logical negation: not operand."""
    def __init__(self, op, operand, span=None):
        self.op = op
        self.operand = operand
        self._set_span(span)

    def __repr__(self):
        return f"LogicalNot({self.op.value} {self.operand})"


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


class WhileNode(SpannedNode):
    """Represents a chaos-aware while loop."""
    def __init__(self, condition, body, span=None):
        self.condition = condition
        self.body = body
        self._set_span(span)

    def __repr__(self):
        return f"While({self.condition}, body={self.body})"


class ForNode(SpannedNode):
    """Represents an inclusive counted loop with a lexical counter."""
    def __init__(
        self,
        counter,
        start,
        stop,
        body,
        step=None,
        counter_span=None,
        span=None,
    ):
        self.counter = counter
        self.start = start
        self.stop = stop
        self.body = body
        self.step = step
        self.counter_span = counter_span
        self._set_span(span)

    def __repr__(self):
        step = f", step={self.step}" if self.step is not None else ""
        return (
            f"For({self.counter}, {self.start} to {self.stop}{step}, "
            f"body={self.body})"
        )


class BreakNode(SpannedNode):
    """Exits the nearest enclosing loop."""
    def __init__(self, span=None):
        self._set_span(span)

    def __repr__(self):
        return "Break()"


class ContinueNode(SpannedNode):
    """Continues the nearest enclosing loop."""
    def __init__(self, span=None):
        self._set_span(span)

    def __repr__(self):
        return "Continue()"


class ProgramNode(SpannedNode):
    """Represents a program with multiple statements"""
    def __init__(self, statements, span=None):
        self.statements = statements
        self._set_span(span)

    def __repr__(self):
        return f"Program({self.statements})"
