"""Calculator Skill for Shaka.

Provides mathematical calculation capabilities including basic arithmetic,
expression evaluation, and common mathematical functions.
"""

import math
import re
from shaka.i18n import gettext as _

class SkillHandler:
    def __init__(self):
        """Initialize the calculator skill."""
        # Safe math functions and constants
        self.safe_dict = {
            'abs': abs, 'round': round, 'min': min, 'max': max,
            'sum': sum, 'pow': pow, 'int': int, 'float': float,
            'ceil': math.ceil, 'floor': math.floor,
            'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
            'asin': math.asin, 'acos': math.acos, 'atan': math.atan,
            'sinh': math.sinh, 'cosh': math.cosh, 'tanh': math.tanh,
            'log': math.log, 'log10': math.log10, 'log2': math.log2,
            'exp': math.exp, 'sqrt': math.sqrt,
            'pi': math.pi, 'e': math.e,
            'degrees': math.degrees, 'radians': math.radians,
        }
    
    def get_tool_def(self):
        """Return the tool definition for LLM consumption."""
        return {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "Perform mathematical calculations and evaluate expressions",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "The mathematical expression to evaluate (e.g., '2 + 2', 'sqrt(16)', 'sin(pi/2)')"
                        },
                        "precision": {
                            "type": "integer",
                            "description": "Number of decimal places for the result (default: 2)",
                            "default": 2,
                            "minimum": 0,
                            "maximum": 10
                        }
                    },
                    "required": ["expression"]
                }
            }
        }
    
    def run(self, message: str, context: dict) -> str:
        """Main entry point for the calculator skill."""
        # Extract parameters from context
        kwargs = context.get("kwargs", {})
        expression = kwargs.get("expression", "").strip()
        precision = kwargs.get("precision", 2)
        
        if not expression:
            return _("Please provide a mathematical expression to calculate.")
        
        try:
            # Clean the expression
            expression = expression.replace(',', '.')  # Handle comma as decimal separator
            
            # Validate expression for safety (only allow safe characters and functions)
            if not self._is_safe_expression(expression):
                return _("Error: Expression contains unsafe characters or functions.")
            
            # Evaluate the expression
            result = self._evaluate_expression(expression)
            
            # Format the result
            if isinstance(result, float):
                # Check if it's effectively an integer
                if result.is_integer():
                    formatted_result = str(int(result))
                else:
                    formatted_result = f"{result:.{precision}f}".rstrip('0').rstrip('.')
            else:
                formatted_result = str(result)
            
            return _("Result: {}").format(formatted_result)
            
        except ZeroDivisionError:
            return _("Error: Division by zero.")
        except OverflowError:
            return _("Error: Result too large to compute.")
        except ValueError as e:
            if "math domain error" in str(e):
                return _("Error: Mathematical domain error (e.g., sqrt of negative number).")
            return _("Error: Invalid value for operation.")
        except Exception as e:
            return _("Error: Could not calculate expression. {}").format(str(e))
    
    def _is_safe_expression(self, expr: str) -> bool:
        """Check if the expression contains only safe characters and functions."""
        # Remove spaces for easier checking
        expr_no_spaces = re.sub(r'\s+', '', expr)
        
        # Check for dangerous patterns
        dangerous_patterns = [
            r'import', r'exec', r'eval', r'open', r'file', r'__',
            r'\\\\', r'`', r';', r'\|\|', r'&&', r'<', r'>',
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, expr_no_spaces, re.IGNORECASE):
                return False
        
        # Check that all characters are allowed
        allowed_chars = set('0123456789.+-*/^()%,abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_')
        for char in expr_no_spaces:
            if char not in allowed_chars:
                return False
        
        return True
    
    def _evaluate_expression(self, expr: str):
        """Safely evaluate a mathematical expression."""
        # Replace common mathematical notation
        expr = expr.replace('^', '**')  # Exponentiation

        # Handle percentage (convert x% to x/100)
        expr = re.sub(r'(\d+(?:\.\d+)?)%', lambda m: f"({m.group(1)}/100)", expr)

        # Prepare the evaluation environment
        env = self.safe_dict.copy()

        # Evaluate the expression
        try:
            result = eval(expr, {"__builtins__": {}}, env)
            return result
        except NameError as e:
            # Try to provide a helpful error message for undefined functions/variables
            msg = str(e)
            if "name '" in msg and "' is not defined" in msg:
                # Extract the undefined name
                import re
                match = re.search(r"name '([^']+)' is not defined", msg)
                if match:
                    undefined_name = match.group(1)
                    if undefined_name not in self.safe_dict:
                        raise NameError(_("Unknown function or variable: {}").format(undefined_name))
            raise
