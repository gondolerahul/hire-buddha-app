"""
Calculator Tool for HireBuddha AI Platform.

Provides safe mathematical expression evaluation using Python's AST
and operator modules instead of unsafe eval().
"""

import ast
import operator
from typing import Dict, Any
from src.ai.tools.base import Tool


class CalculatorTool(Tool):
    """Safe calculator tool for mathematical expressions.
    
    Supports:
        - Basic arithmetic: +, -, *, /, //, %, **
        - Parentheses for grouping
        - Negative numbers
        - Decimal numbers
    
    Examples:
        - "2 + 2" -> "4"
        - "(10 + 5) * 3" -> "45"
        - "2 ** 10" -> "1024"
        - "17 % 5" -> "2"
    """
    
    name = "calculator"
    description = (
        "Performs mathematical calculations safely. "
        "Input should be a mathematical expression like '2 + 2' or '(10 * 5) / 2'. "
        "Supports: +, -, *, /, //, %, ** (power), and parentheses."
    )

    # Allowed operators for safe evaluation
    _operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def _safe_eval(self, node: ast.AST) -> float:
        """Recursively evaluate an AST node safely.
        
        Args:
            node: AST node to evaluate
            
        Returns:
            Numeric result of evaluation
            
        Raises:
            ValueError: If node type is not supported
        """
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"Unsupported constant type: {type(node.value)}")
        
        elif isinstance(node, ast.BinOp):
            left = self._safe_eval(node.left)
            right = self._safe_eval(node.right)
            op = self._operators.get(type(node.op))
            if op is None:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            
            # Prevent division by zero
            if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
                raise ValueError("Division by zero")
            
            # Prevent extremely large exponents
            if isinstance(node.op, ast.Pow) and abs(right) > 1000:
                raise ValueError("Exponent too large (max 1000)")
                
            return op(left, right)
        
        elif isinstance(node, ast.UnaryOp):
            operand = self._safe_eval(node.operand)
            op = self._operators.get(type(node.op))
            if op is None:
                raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
            return op(operand)
        
        elif isinstance(node, ast.Expression):
            return self._safe_eval(node.body)
        
        else:
            raise ValueError(f"Unsupported expression type: {type(node).__name__}")

    async def run(self, input_data: str) -> str:
        """Evaluate a mathematical expression safely.
        
        Args:
            input_data: Mathematical expression string
            
        Returns:
            String representation of the result
        """
        try:
            # Clean input
            expression = input_data.strip()
            if not expression:
                return "Error: Empty expression"
            
            # Parse expression into AST
            tree = ast.parse(expression, mode='eval')
            
            # Evaluate safely
            result = self._safe_eval(tree)
            
            # Format result (remove trailing zeros for floats)
            if isinstance(result, float) and result.is_integer():
                return str(int(result))
            return str(result)
            
        except SyntaxError as e:
            return f"Error: Invalid expression syntax - {str(e)}"
        except ValueError as e:
            return f"Error: {str(e)}"
        except Exception as e:
            return f"Error calculating: {str(e)}"

    def get_function_schema(self) -> Dict[str, Any]:
        """Return JSON schema for function calling."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression to evaluate (e.g., '2 + 2', '(10 * 5) / 2')"
                    }
                },
                "required": ["expression"]
            }
        }
