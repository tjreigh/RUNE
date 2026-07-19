from tokens import TokenType
from ast_nodes import (
    BinaryOpNode,
    NumberNode,
    StringNode,
    ComparisonNode,
    ChaosPragmaNode,
    VariableNode,
    AssignmentNode,
    GroupNode,
    UnaryOpNode,
    IfNode,
    ProgramNode,
)
from diagnostics import RuneInternalError, RuneLimitError, RuneRuntimeError
from runtime_state import RuntimeState, RuntimeEvent
from limits import ExecutionLimits, ExecutionStats

class Interpreter:
    """
    Tree-walking interpreter for RUNE
    Visits each node in the AST and computes the result against a
    RuntimeState, recording structured RuntimeEvents instead of printing,
    while enforcing deterministic step/recursion/output budgets.
    """

    def __init__(self, state=None, limits=None):
        self.state = state if state is not None else RuntimeState()
        self.events = []
        self.limits = limits if limits is not None else ExecutionLimits()
        self._steps = 0
        self._depth = 0
        self._peak_depth = 0
        self._output_count = 0

    @property
    def stats(self):
        """Work performed so far, valid whether or not execution succeeded."""
        return ExecutionStats(
            steps=self._steps,
            peak_recursion_depth=self._peak_depth,
            output_values=self._output_count,
        )

    def _emit(self, value, span):
        """Count one output value against the output budget. Unlike steps
        and recursion depth, a rejected value was never actually emitted,
        so the counter (and reported stats) only reflect accepted values."""
        if self._output_count + 1 > self.limits.max_output_values:
            raise RuneLimitError("Output budget exceeded", span)
        self._output_count += 1
        return value

    def visit(self, node):
        """Dispatch to appropriate visit method based on node type"""
        self._steps += 1
        if self._steps > self.limits.max_steps:
            raise RuneLimitError("Step budget exceeded", getattr(node, "span", None))

        self._depth += 1
        if self._depth > self._peak_depth:
            self._peak_depth = self._depth

        try:
            if self._depth > self.limits.max_recursion_depth:
                raise RuneLimitError(
                    "Recursion depth exceeded", getattr(node, "span", None)
                )

            if isinstance(node, NumberNode):
                return self.visit_number(node)
            elif isinstance(node, StringNode):
                return self.visit_string(node)
            elif isinstance(node, BinaryOpNode):
                return self.visit_binop(node)
            elif isinstance(node, ComparisonNode):
                return self.visit_comparison(node)
            elif isinstance(node, ChaosPragmaNode):
                return self.visit_chaos_pragma(node)
            elif isinstance(node, VariableNode):
                return self.visit_variable(node)
            elif isinstance(node, AssignmentNode):
                return self.visit_assignment(node)
            elif isinstance(node, GroupNode):
                return self.visit_group(node)
            elif isinstance(node, UnaryOpNode):
                return self.visit_unary(node)
            elif isinstance(node, IfNode):
                return self.visit_if(node)
            elif isinstance(node, ProgramNode):
                return self.visit_program(node)
            else:
                raise RuneInternalError(
                    f"Unknown node type: {type(node).__name__}",
                    getattr(node, "span", None),
                )
        finally:
            self._depth -= 1

    def visit_number(self, node):
        """A number is just its value"""
        return node.value

    def visit_string(self, node):
        """THE RUNE MAGIC: Convert string to sum of ASCII values"""
        return sum(ord(c) for c in node.value)

    def visit_group(self, node):
        """Evaluate a parenthesized expression without changing its value."""
        return self.visit(node.expression)

    def visit_unary(self, node):
        """Evaluate numeric negation or infinite-width bitwise complement."""
        operand = self.visit(node.operand)
        if node.op.type == TokenType.MINUS:
            return -operand
        elif node.op.type == TokenType.BIT_NOT:
            return ~operand
        raise RuneInternalError(
            f"Unknown unary operator: {node.op.type.value}", node.op.span
        )

    def visit_binop(self, node):
        """Evaluate binary operation"""
        # Recursively evaluate left and right
        left = self.visit(node.left)
        right = self.visit(node.right)

        # Perform the operation
        if node.op.type == TokenType.PLUS:
            return left + right
        elif node.op.type == TokenType.MINUS:
            return left - right
        elif node.op.type == TokenType.MULT:
            return left * right
        else:
            raise RuneInternalError(
                f"Unknown operator: {node.op.type.value}", node.op.span
            )

    def visit_comparison(self, node):
        """Evaluate comparison operation - returns 1 or 0"""
        # Recursively evaluate left and right
        left = self.visit(node.left)
        right = self.visit(node.right)

        # Perform the comparison
        if node.op.type == TokenType.LT:
            result = left < right
        elif node.op.type == TokenType.GT:
            result = left > right
        elif node.op.type == TokenType.LTE:
            result = left <= right
        elif node.op.type == TokenType.GTE:
            result = left >= right
        elif node.op.type == TokenType.EQ:
            result = left == right
        elif node.op.type == TokenType.NEQ:
            result = left != right
        else:
            raise RuneInternalError(
                f"Unknown comparison operator: {node.op.type.value}", node.op.span
            )

        # Return 1 for truthy, 0 for falsy
        return 1 if result else 0

    def visit_chaos_pragma(self, node):
        """Handle @chaos pragma - replaces the working state and records
        a structured event instead of printing."""
        self.state = self.state.with_chaos_threshold(node.threshold)
        self.events.append(
            RuntimeEvent(
                kind="chaos_threshold_changed",
                data={"threshold": node.threshold},
                span=node.span,
            )
        )
        # Pragmas don't produce a value
        return None

    def visit_variable(self, node):
        """Look up an already-collapsed numeric variable value."""
        variables = self.state.variables
        if node.name not in variables:
            raise RuneRuntimeError(f"Undefined variable '{node.name}'", node.span)
        return variables[node.name]

    def visit_assignment(self, node):
        """Evaluate and commit one numeric value to the working state.

        String literals collapse while evaluating the right-hand side, so the
        environment never stores a separate string runtime type.
        """
        value = self.visit(node.value)
        variables = self.state.variables
        if node.name not in variables and len(variables) >= self.limits.max_variables:
            raise RuneLimitError("Variable budget exceeded", node.span)
        self.state = self.state.with_variable(node.name, value)
        self.events.append(
            RuntimeEvent(
                kind="variable_assigned",
                data={"name": node.name, "value": value},
                span=node.span,
            )
        )
        return None

    def is_chaos_truthy(self, value):
        """Apply the current chaos threshold to a numeric value."""
        if value <= 0:
            return False
        return value >= self.state.chaos_threshold

    def _exec_block(self, statements):
        """Execute statements and flatten values produced by nested blocks.

        A nested block's own values arrive here already flattened (as a
        list), so only the non-list, non-None branch below emits a *new*
        output value; extending a nested list must not count it again.
        """
        results = []
        for stmt in statements:
            result = self.visit(stmt)
            if result is None:
                continue
            if isinstance(result, list):
                results.extend(result)
            else:
                results.append(self._emit(result, stmt.span))
        return results

    def visit_if(self, node):
        """Execute the first conditional branch that clears the chaos threshold."""
        if self.is_chaos_truthy(self.visit(node.condition)):
            return self._exec_block(node.then_block)

        for condition, statements in node.elif_clauses:
            if self.is_chaos_truthy(self.visit(condition)):
                return self._exec_block(statements)

        if node.else_block is not None:
            return self._exec_block(node.else_block)
        return []

    def visit_program(self, node):
        """Execute a program with multiple statements"""
        return self._exec_block(node.statements)

    def interpret(self, ast):
        """Main entry point for interpretation. A bare top-level expression
        (not wrapped in a ProgramNode) never passes through _exec_block, so
        it is emitted here instead; a list or None result has already been
        accounted for further down and is returned unchanged."""
        raw = self.visit(ast)
        if raw is None or isinstance(raw, list):
            return raw
        return self._emit(raw, ast.span)
