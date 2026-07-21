"""
Safe formula evaluator — the heart of the DB-driven Formula Engine.

Admins write KPI formulas as plain arithmetic over named variables, e.g.:

    (فروش / تارگت) * 100
    فروش_کل - مرجوعی
    (سود / فروش) * 100

Rules:
- Parsed with Python's `ast` in eval mode; ONLY these node types are allowed:
  numbers, variable names, + - * /, unary +/-, parentheses, and the functions
  abs/min/max/round. Everything else (attributes, subscripts, lambdas,
  imports, comprehensions, strings) raises FormulaError — so a formula can
  never execute arbitrary code.
- Persian identifiers are valid Python identifiers, so variables can be named
  in Persian (use _ instead of spaces).
- Division by zero and missing values propagate as None (the workbook's
  #DIV/0! cells become clean NULLs, never crashes).
- All math in Decimal.
"""
from __future__ import annotations

import ast
from decimal import Decimal, InvalidOperation

MAX_LENGTH = 500

_FUNCS = {"abs": abs, "min": min, "max": max, "round": round}


class FormulaError(ValueError):
    """Raised when an expression is syntactically or semantically invalid."""


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def validate(expression: str, variable_names: set[str]) -> None:
    """Raise FormulaError if the expression is invalid or references unknown
    variables. Used by the API's create/test endpoints."""
    evaluate(expression, {name: 1 for name in variable_names}, _validate_only=True)


def evaluate(
    expression: str,
    variables: dict[str, object],
    *,
    _validate_only: bool = False,
) -> Decimal | None:
    """Evaluate `expression` against `variables`. Returns Decimal or None."""
    if not expression or not expression.strip():
        raise FormulaError("فرمول خالی است.")
    if len(expression) > MAX_LENGTH:
        raise FormulaError(f"فرمول بلندتر از {MAX_LENGTH} کاراکتر است.")

    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"خطای نحوی در فرمول: {exc.msg}") from exc

    def ev(node) -> Decimal | None:
        if isinstance(node, ast.Expression):
            return ev(node.body)

        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return Decimal(str(node.value))
            raise FormulaError("فقط اعداد مجاز هستند.")

        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise FormulaError(f"متغیر ناشناخته: {node.id}")
            return _to_decimal(variables[node.id])

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = ev(node.operand)
            if value is None:
                return None
            return -value if isinstance(node.op, ast.USub) else value

        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
        ):
            left, right = ev(node.left), ev(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            # Division: zero denominator -> None (safe), like the KPI engines.
            return None if right == 0 else left / right

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCS
            and not node.keywords
        ):
            args = [ev(a) for a in node.args]
            if any(a is None for a in args):
                return None
            try:
                return _to_decimal(_FUNCS[node.func.id](*args))
            except (TypeError, ValueError) as exc:
                raise FormulaError(f"فراخوانی نامعتبر {node.func.id}: {exc}") from exc

        raise FormulaError(
            f"عنصر غیرمجاز در فرمول: {type(node).__name__} "
            "(فقط اعداد، متغیرها، + - * / و abs/min/max/round مجازند)"
        )

    result = ev(tree)
    return None if _validate_only else result
