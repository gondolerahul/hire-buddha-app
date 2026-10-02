"""
Calculator Tool for HireBuddha AI Platform.

Provides safe mathematical expression evaluation using Python's AST
and operator modules instead of unsafe eval().
"""

import ast
import operator
from typing import Any, Dict

from pydantic import Field, field_validator

from src.ai.tools.base import Tool, ToolOutput, ToolParams


class CalculatorParams(ToolParams):
    expression: str = Field(..., description="Mathematical expression to evaluate (e.g., '2 + 2', '(10 * 5) / 2')")

    @field_validator("expression")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("an empty expression")
        return v.strip()


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
        "Supports: +, -, *, /, //, %, ** (power), and parentheses."
    )
    Params = CalculatorParams
    # A plan step's text is the expression. A model's call gives
    # {"expression": ...}; before P6.10 the tool parsed that whole JSON object
    # as the expression and every model call failed (TL-68).
    string_field = "expression"

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

    async def execute(self, params: "CalculatorParams", ctx: Dict[str, Any]) -> ToolOutput:
        """Evaluate ``params.expression`` (it is parsed, never ``eval``-ed)."""
        try:
            result = self._safe_eval(ast.parse(params.expression, mode="eval"))
        except SyntaxError as e:
            return ToolOutput.failed(f"Invalid expression syntax - {e}", code="invalid_expression")
        except ValueError as e:
            return ToolOutput.failed(str(e), code="invalid_expression")
        except Exception as e:  # noqa: BLE001 - overflow and the like
            return ToolOutput.failed(f"calculating: {e}")
        # 4.0 -> "4"
        if isinstance(result, float) and result.is_integer():
            return ToolOutput(output=str(int(result)))
        return ToolOutput(output=str(result))
