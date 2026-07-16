from tokens import TokenType
from ast_nodes import BinaryOpNode, NumberNode, StringNode, ComparisonNode, ChaosPragmaNode, ProgramNode

class Interpreter:
    """
    Tree-walking interpreter for RUNE
    Visits each node in the AST and computes the result
    """

    def __init__(self):
        self.chaos_threshold = 1  # Default chaos level
        self.verbose = False

    def visit(self, node):
        """Dispatch to appropriate visit method based on node type"""
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
        elif isinstance(node, ProgramNode):
            return self.visit_program(node)
        else:
            raise Exception(f"Unknown node type: {type(node)}")
    
    def visit_number(self, node):
        """A number is just its value"""
        return node.value
    
    def visit_string(self, node):
        """THE RUNE MAGIC: Convert string to sum of ASCII values"""
        return sum(ord(c) for c in node.value)
    
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
            raise Exception(f"Unknown operator: {node.op.type}")

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
            raise Exception(f"Unknown comparison operator: {node.op.type}")

        # Return 1 for truthy, 0 for falsy
        return 1 if result else 0

    def visit_chaos_pragma(self, node):
        """Handle @chaos pragma - updates the chaos threshold"""
        self.chaos_threshold = node.threshold
        if self.verbose:
            print(f"[CHAOS] Threshold set to {self.chaos_threshold}")
        # Pragmas don't produce a value
        return None

    def visit_program(self, node):
        """Execute a program with multiple statements"""
        results = []
        for stmt in node.statements:
            result = self.visit(stmt)
            # Collect non-None results (pragmas return None)
            if result is not None:
                results.append(result)
        # Return list of all results
        return results

    def interpret(self, ast):
        """Main entry point for interpretation"""
        return self.visit(ast)
