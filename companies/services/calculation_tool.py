"""
Tool `calculer` de l'agent du questionnaire : les LLM se trompent souvent en arithmétique, alors
que l'agent compare sans cesse des chiffres (écart entre CA publié et factures, jours de retard,
intérêts...). Le LLM écrit le calcul ; le tool en donne le résultat exact.

Le tool ne fait confiance au LLM que pour la formule, pas pour le calcul. Les pertes à chiffrer
pour de bon passeront par des formules écrites et validées par l'expert métier (`estimer_impact`).

L'expression n'est jamais exécutée (ni `eval` ni `exec`) : elle est découpée en arbre (`ast`) et
seuls les nombres, + - * / **, les parenthèses et quelques fonctions (min, max, abs, round) sont
calculés ; tout le reste (nom, appel d'une autre fonction, attribut, chaîne...) est refusé. Les
nombres sont calculés en flottants : un résultat trop grand lève une erreur au lieu de bloquer le
serveur (9 ** 9 ** 9 en entiers prendrait des minutes).

Une erreur (expression invalide, division par zéro...) est renvoyée au LLM pour ce calcul seulement,
sous la forme {"erreur": "..."} : les autres calculs du même appel sont faits.
"""
import ast
import json
import math
import operator

from langchain_core.tools import tool
from pydantic import BaseModel, Field

MAX_CALCULATIONS = 10
MAX_EXPRESSION_LENGTH = 300
DECIMALS = 6  # 0.1 + 0.2 donne 0.3, pas 0.30000000000000004

BINARY_OPERATIONS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
UNARY_OPERATIONS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
# % et // sont exclus : « 10 % » se lirait comme un modulo.


def rounded(value: float, decimals: float = 0) -> float:
    if not float(decimals).is_integer():
        raise TypeError
    return round(value, int(decimals))


FUNCTIONS = {'min': min, 'max': max, 'abs': abs, 'round': rounded}

SYNTAX_HINT = (
    'écrire les nombres sans espace ni séparateur de milliers (1200000), le point pour les décimales '
    '(0.10), un pourcentage en décimal (10 % -> 0.10), avec + - * / ** et des parenthèses'
)

CALCULATION_TOOL_NAME = 'calculer'
CALCULATION_TOOL_DESCRIPTION = (
    "Calcule exactement des expressions arithmétiques : à utiliser pour tout calcul (écart, ratio, "
    "pourcentage, total, jours de retard, intérêts...) au lieu de le faire de tête. Jusqu'à "
    f"{MAX_CALCULATIONS} calculs par appel, chacun avec un libellé. Autorisés : nombres (point "
    "décimal, sans séparateur de milliers : 1200000.50), + - * / ** (puissance), parenthèses, "
    "min(...), max(...), abs(x), round(x, décimales). Un pourcentage s'écrit en décimal (10 % -> "
    "0.10). Pas de variable : remplacer chaque donnée par sa valeur. Ex. : écart en % entre CA "
    "publié et total des factures -> (1200000 - 870000) / 1200000 * 100. Renvoie pour chaque "
    f"calcul son résultat (arrondi à {DECIMALS} décimales) ou une erreur."
)


class Calculation(BaseModel):
    libelle: str = Field(description='Ce que le calcul mesure. Ex. : "écart CA publié / factures (%)".')
    expression: str = Field(description='Expression arithmétique. Ex. : "(1200000 - 870000) / 1200000 * 100".')


class CalculationArguments(BaseModel):
    calculs: list[Calculation] = Field(description=f'Calculs à faire, {MAX_CALCULATIONS} au maximum.')


class CalculationError(Exception):
    """Expression refusée ou impossible à calculer ; le message est renvoyé au LLM."""


def evaluate_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        raise CalculationError(f'valeur non numérique : {node.value!r}')
    if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPERATIONS:
        return BINARY_OPERATIONS[type(node.op)](evaluate_node(node.left), evaluate_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPERATIONS:
        return UNARY_OPERATIONS[type(node.op)](evaluate_node(node.operand))
    if isinstance(node, ast.Call):
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name not in FUNCTIONS:
            raise CalculationError(f"fonction non autorisée (autorisées : {', '.join(FUNCTIONS)})")
        if node.keywords or not node.args:
            raise CalculationError(f'arguments invalides pour {name}')
        arguments = [evaluate_node(argument) for argument in node.args]
        try:
            return float(FUNCTIONS[name](*arguments))
        except TypeError:
            raise CalculationError(f'arguments invalides pour {name}') from None
    if isinstance(node, ast.Name):
        raise CalculationError(f'« {node.id} » inconnu : remplacer chaque donnée par sa valeur numérique')
    if isinstance(node, ast.Tuple):
        raise CalculationError(f'virgule inattendue : {SYNTAX_HINT}')
    if isinstance(node, ast.BinOp):
        raise CalculationError('opérateur non autorisé (autorisés : + - * / **)')
    raise CalculationError(f'élément non autorisé : {SYNTAX_HINT}')


def evaluate(expression: str) -> float:
    """Résultat de l'expression, arrondi à DECIMALS décimales. Lève CalculationError."""
    if not isinstance(expression, str) or not expression.strip():
        raise CalculationError('expression vide')
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise CalculationError(f'expression trop longue ({MAX_EXPRESSION_LENGTH} caractères au maximum) : la découper')
    try:
        tree = ast.parse(expression.strip(), mode='eval')
    except SyntaxError:
        raise CalculationError(f'expression invalide : {SYNTAX_HINT}') from None
    except (RecursionError, MemoryError, ValueError):
        raise CalculationError('expression trop imbriquée') from None
    try:
        value = evaluate_node(tree.body)
    except ZeroDivisionError:
        raise CalculationError('division par zéro') from None
    except OverflowError:
        raise CalculationError('résultat trop grand') from None
    except RecursionError:
        raise CalculationError('expression trop imbriquée') from None
    if isinstance(value, complex) or not math.isfinite(value):
        # (-8) ** 0.5 donne un complexe
        raise CalculationError('résultat non réel ou infini')
    value = round(value, DECIMALS)
    return int(value) if value.is_integer() and abs(value) < 1e15 else value


def calculate(calculations) -> dict:
    """
    Résultats des calculs : [{libelle, expression, resultat | erreur}].
    `calculations` : objets Calculation ou dictionnaires {libelle, expression}.
    """
    calculations = list(calculations or [])
    if not calculations:
        return {'erreur': 'Aucun calcul demandé.'}
    if len(calculations) > MAX_CALCULATIONS:
        return {'erreur': f'{MAX_CALCULATIONS} calculs au maximum par appel ({len(calculations)} reçus).'}
    results = []
    for calculation in calculations:
        if isinstance(calculation, BaseModel):
            calculation = calculation.model_dump()
        label, expression = calculation.get('libelle'), calculation.get('expression')
        result = {'libelle': label, 'expression': expression}
        try:
            result['resultat'] = evaluate(expression)
        except CalculationError as error:
            result['erreur'] = str(error)
        results.append(result)
    return {'resultats': results}


@tool(CALCULATION_TOOL_NAME, description=CALCULATION_TOOL_DESCRIPTION, args_schema=CalculationArguments)
def calculer(calculs: list[Calculation]) -> str:
    return json.dumps(calculate(calculs), ensure_ascii=False)
