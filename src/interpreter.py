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
from diagnostics import RuneInternalError, RuneLimitError, RuneRuntimeError
from runtime_state import RuntimeState, RuntimeEvent
from limits import ExecutionLimits, ExecutionStats
from bindings import BindingEnvironment


class _LoopControlSignal(Exception):
    """Private non-local control flow carrying values already produced."""

    def __init__(self):
        super().__init__()
        self.values = []


class _BreakSignal(_LoopControlSignal):
    pass


class _ContinueSignal(_LoopControlSignal):
    pass


class Interpreter:
    """
    Tree-walking interpreter for RUNE
    Visits each node in the AST and computes the result against a
    RuntimeState, recording structured RuntimeEvents instead of printing,
    while enforcing deterministic work, state, output, and integer budgets.
    """

    def __init__(self, state=None, limits=None):
        self.state = state if state is not None else RuntimeState()
        self.events = []
        self.limits = limits if limits is not None else ExecutionLimits()
        self._steps = 0
        self._depth = 0
        self._peak_depth = 0
        self._output_count = 0
        self._event_count = 0
        self._loop_iterations = 0
        self._bindings = BindingEnvironment()

    @property
    def stats(self):
        """Work performed so far, valid whether or not execution succeeded."""
        return ExecutionStats(
            steps=self._steps,
            peak_recursion_depth=self._peak_depth,
            output_values=self._output_count,
            runtime_events=self._event_count,
            loop_iterations=self._loop_iterations,
        )

    def _tick(self, span):
        """Charge one deterministic unit of interpreter work."""
        self._steps += 1
        if self._steps > self.limits.max_steps:
            raise RuneLimitError("Step budget exceeded", span)

    def _begin_loop_iteration(self, span):
        """Charge and record one iteration immediately before body entry."""
        self._tick(span)
        self._loop_iterations += 1

    def _record_event(self, event):
        """Append one event within the serialized event-count budget."""
        if self._event_count + 1 > self.limits.max_events:
            raise RuneLimitError("Event budget exceeded", event.span)
        self.events.append(event)
        self._event_count += 1

    def _emit(self, value, span):
        """Count one output value against the output budget. Unlike steps
        and recursion depth, a rejected value was never actually emitted,
        so the counter (and reported stats) only reflect accepted values."""
        self._check_integer(value, span)
        if self._output_count + 1 > self.limits.max_output_values:
            raise RuneLimitError("Output budget exceeded", span)
        self._output_count += 1
        return value

    def _check_integer(self, value, span):
        """Enforce the runtime integer invariant at value boundaries."""
        if value.bit_length() > self.limits.max_integer_bits:
            raise RuneLimitError(
                "Integer magnitude exceeds the "
                f"{self.limits.max_integer_bits}-bit limit",
                span,
            )
        return value

    def _check_state(self):
        """Reject state created under a looser limit before evaluating it."""
        self._check_integer(self.state.chaos_threshold, None)
        variables = self.state.variables
        if len(variables) > self.limits.max_variables:
            raise RuneLimitError("Variable budget exceeded", None)
        for value in variables.values():
            self._check_integer(value, None)

    def _binding_scope(
        self,
        values=None,
        captures_assignments=False,
        span=None,
    ):
        """Create an ephemeral lexical frame within the variable budget."""
        values = dict(values or {})
        for value in values.values():
            self._check_integer(value, span)
        total_bindings = (
            len(self.state.variables)
            + self._bindings.binding_count
            + len(values)
        )
        if total_bindings > self.limits.max_variables:
            raise RuneLimitError("Variable budget exceeded", span)
        return self._bindings.frame(values, captures_assignments)

    def _checked_multiply(self, left, right, span):
        """Reject a definitely oversized product before allocating it.

        For nonzero integers the result uses either L+R-1 or L+R bits. If
        the lower bound fits, constructing the product can exceed the budget
        by at most one bit, after which the exact check decides the boundary.
        """
        if left and right:
            minimum_result_bits = left.bit_length() + right.bit_length() - 1
            if minimum_result_bits > self.limits.max_integer_bits:
                raise RuneLimitError(
                    "Integer magnitude exceeds the "
                    f"{self.limits.max_integer_bits}-bit limit",
                    span,
                )
        return self._check_integer(left * right, span)

    def _checked_power(self, base, exponent, span):
        """Reject invalid or definitely oversized powers before allocation.

        For |base| >= 2, ``exponent * (bit_length(base) - 1) + 1`` is a
        lower bound on the result's bit length. If that bound fits, the exact
        result is less than twice the configured bit budget, so it is safe to
        construct and check precisely.
        """
        if exponent < 0:
            raise RuneRuntimeError("Negative exponent", span)
        if abs(base) >= 2 and exponent:
            minimum_result_bits = exponent * (base.bit_length() - 1) + 1
            if minimum_result_bits > self.limits.max_integer_bits:
                raise RuneLimitError(
                    "Integer magnitude exceeds the "
                    f"{self.limits.max_integer_bits}-bit limit",
                    span,
                )
        return self._check_integer(base ** exponent, span)

    @staticmethod
    def _truncating_division(dividend, divisor, span):
        """Divide integers without float conversion, truncating toward zero."""
        if divisor == 0:
            raise RuneRuntimeError("Division by zero", span)
        quotient = abs(dividend) // abs(divisor)
        if (dividend < 0) != (divisor < 0):
            quotient = -quotient
        return quotient

    def _signed_remainder(self, dividend, divisor, span):
        """Return the remainder paired with truncation-toward-zero division."""
        if divisor == 0:
            raise RuneRuntimeError("Modulo by zero", span)
        quotient = self._truncating_division(dividend, divisor, span)
        return dividend - quotient * divisor

    def _checked_left_shift(self, value, count, span):
        """Reject invalid or oversized left shifts before allocation."""
        if count < 0:
            raise RuneRuntimeError("Negative shift count", span)
        if value == 0:
            return 0
        result_bits = value.bit_length() + count
        if result_bits > self.limits.max_integer_bits:
            raise RuneLimitError(
                "Integer magnitude exceeds the "
                f"{self.limits.max_integer_bits}-bit limit",
                span,
            )
        return self._check_integer(value << count, span)

    @staticmethod
    def _bounded_right_shift(value, count, span):
        """Avoid passing an astronomically large count into CPython's shift."""
        if count < 0:
            raise RuneRuntimeError("Negative shift count", span)
        if count >= value.bit_length():
            return -1 if value < 0 else 0
        return value >> count

    def visit(self, node):
        """Dispatch to appropriate visit method based on node type"""
        self._tick(getattr(node, "span", None))

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
            elif isinstance(node, LogicalOpNode):
                return self.visit_logical_op(node)
            elif isinstance(node, LogicalNotNode):
                return self.visit_logical_not(node)
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
        return self._check_integer(node.value, node.span)

    def visit_string(self, node):
        """THE RUNE MAGIC: Convert string to sum of ASCII values"""
        return self._check_integer(sum(ord(c) for c in node.value), node.span)

    def visit_group(self, node):
        """Evaluate a parenthesized expression without changing its value."""
        return self.visit(node.expression)

    def visit_unary(self, node):
        """Evaluate numeric negation or infinite-width bitwise complement."""
        operand = self.visit(node.operand)
        if node.op.type == TokenType.MINUS:
            return self._check_integer(-operand, node.op.span)
        elif node.op.type == TokenType.BIT_NOT:
            return self._check_integer(~operand, node.op.span)
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
            return self._check_integer(left + right, node.op.span)
        elif node.op.type == TokenType.MINUS:
            return self._check_integer(left - right, node.op.span)
        elif node.op.type == TokenType.MULT:
            return self._checked_multiply(left, right, node.op.span)
        elif node.op.type == TokenType.DIV:
            return self._check_integer(
                self._truncating_division(left, right, node.op.span),
                node.op.span,
            )
        elif node.op.type == TokenType.MOD:
            return self._check_integer(
                self._signed_remainder(left, right, node.op.span),
                node.op.span,
            )
        elif node.op.type == TokenType.POWER:
            return self._checked_power(left, right, node.op.span)
        elif node.op.type == TokenType.BIT_AND:
            return self._check_integer(left & right, node.op.span)
        elif node.op.type == TokenType.BIT_OR:
            return self._check_integer(left | right, node.op.span)
        elif node.op.type == TokenType.BIT_XOR:
            return self._check_integer(left ^ right, node.op.span)
        elif node.op.type == TokenType.SHIFT_LEFT:
            return self._checked_left_shift(left, right, node.op.span)
        elif node.op.type == TokenType.SHIFT_RIGHT:
            return self._check_integer(
                self._bounded_right_shift(left, right, node.op.span),
                node.op.span,
            )
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

    def visit_logical_op(self, node):
        """Evaluate AND/OR lazily and normalize the result to 1 or 0."""
        left_is_truthy = self.is_chaos_truthy(self.visit(node.left))

        if node.op.type == TokenType.AND:
            if not left_is_truthy:
                return 0
            return 1 if self.is_chaos_truthy(self.visit(node.right)) else 0

        if node.op.type == TokenType.OR:
            if left_is_truthy:
                return 1
            return 1 if self.is_chaos_truthy(self.visit(node.right)) else 0

        raise RuneInternalError(
            f"Unknown logical operator: {node.op.type.value}", node.op.span
        )

    def visit_logical_not(self, node):
        """Negate one chaos-truthiness result and normalize to 1 or 0."""
        if node.op.type != TokenType.NOT:
            raise RuneInternalError(
                f"Unknown logical operator: {node.op.type.value}", node.op.span
            )
        return 0 if self.is_chaos_truthy(self.visit(node.operand)) else 1

    def visit_chaos_pragma(self, node):
        """Handle @chaos pragma - replaces the working state and records
        a structured event instead of printing."""
        threshold = self._check_integer(node.threshold, node.span)
        self.state = self.state.with_chaos_threshold(threshold)
        self._record_event(
            RuntimeEvent(
                kind="chaos_threshold_changed",
                data={"threshold": threshold},
                span=node.span,
            )
        )
        # Pragmas don't produce a value
        return None

    def visit_variable(self, node):
        """Look up an already-collapsed numeric variable value."""
        try:
            value = self._bindings.resolve(node.name, self.state.variables)
        except KeyError:
            raise RuneRuntimeError(f"Undefined variable '{node.name}'", node.span)
        return self._check_integer(value, node.span)

    def visit_assignment(self, node):
        """Evaluate and commit one numeric value to the working state.

        String literals collapse while evaluating the right-hand side, so the
        environment never stores a separate string runtime type.
        """
        value = self.visit(node.value)
        self._check_integer(value, node.value.span)
        local_frame = self._bindings.assignment_target(node.name)
        if local_frame is not None:
            if (
                node.name not in local_frame.values
                and len(self.state.variables) + self._bindings.binding_count
                >= self.limits.max_variables
            ):
                raise RuneLimitError("Variable budget exceeded", node.span)
            local_frame.values[node.name] = value
        else:
            variables = self.state.variables
            if (
                node.name not in variables
                and len(variables) + self._bindings.binding_count
                >= self.limits.max_variables
            ):
                raise RuneLimitError("Variable budget exceeded", node.span)
            self.state = self.state.with_variable(node.name, value)
        self._record_event(
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
            try:
                result = self.visit(stmt)
            except _LoopControlSignal as signal:
                signal.values[0:0] = results
                raise
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
        self._check_state()
        raw = self.visit(ast)
        if raw is None or isinstance(raw, list):
            return raw
        return self._emit(raw, ast.span)
