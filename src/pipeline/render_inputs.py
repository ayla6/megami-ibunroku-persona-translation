"""Cache code dependencies of a renderer without its unrelated command driver.

Local helper functions and referenced scalar constants are included. Imported
modules remain whole-file inputs. Dynamic global lookup or unsupported global
state falls back to the complete defining module, favoring invalidation.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
import textwrap
from types import CodeType, FunctionType, ModuleType

import build_step_cache


def global_names(code: CodeType) -> set[str]:
    names = set(code.co_names)
    for constant in code.co_consts:
        if isinstance(constant, CodeType):
            names.update(global_names(constant))
    return names


def fingerprint(root: FunctionType, context: tuple[str, ...] = (), *,
                data_globals: frozenset[str] = frozenset()) -> str:
    """data_globals name inputs whose contents the caller fingerprints separately."""
    pending = [root]
    seen: set[str] = set()
    fragments: dict[str, str] = {}
    paths: set[Path] = {Path(__file__)}
    while pending:
        function = pending.pop()
        module_path = inspect.getsourcefile(function)
        if module_path is None:
            raise ValueError('renderer source is unavailable')
        module_name = str(Path(module_path).resolve())
        identifier = module_name + ':' + function.__qualname__
        if identifier in seen:
            continue
        seen.add(identifier)
        try:
            tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
        except (OSError, TypeError, SyntaxError):
            paths.add(Path(module_path))
            continue
        fragments[identifier] = ast.dump(tree, include_attributes=False)
        fragments[identifier + '.defaults'] = repr((function.__defaults__, function.__kwdefaults__))
        names = global_names(function.__code__)
        if names & {'globals', 'locals', 'eval', 'exec', '__import__', 'getattr'}:
            paths.add(Path(module_path))
        for name in sorted(names):
            if name in data_globals or name not in function.__globals__:
                continue  # Builtins are covered by the interpreter fingerprint.
            value = function.__globals__[name]
            if isinstance(value, FunctionType) and value.__module__ == function.__module__:
                pending.append(value)
            elif isinstance(value, ModuleType):
                if value.__file__:
                    paths.add(Path(value.__file__))
                if hasattr(value, '__version__'):
                    fragments[name + '.version'] = str(value.__version__)
            elif isinstance(value, (str, bytes, int, float, bool, type(None))):
                fragments[module_name + ':' + name] = repr(value)
            elif isinstance(value, FunctionType):
                imported = inspect.getsourcefile(value)
                if imported:
                    paths.add(Path(imported))
                else:
                    paths.add(Path(module_path))
            else:
                paths.add(Path(module_path))
    return build_step_cache.fingerprint(sorted(paths), context=(
        *context, repr(sorted(data_globals)),
        *(name + '\0' + fragment for name, fragment in sorted(fragments.items()))))
