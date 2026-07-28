"""Executable dependency rules for the internal Python architecture."""

import ast
from collections import defaultdict
from pathlib import Path


def _module_name(path: Path, source_root: Path) -> str:
    module = ".".join(path.relative_to(source_root).with_suffix("").parts)
    return module.removesuffix(".__init__")


def _internal_dependency_graph(source_root: Path) -> dict[str, set[str]]:
    modules = {
        _module_name(path, source_root): path for path in (source_root / "scribe").rglob("*.py")
    }
    graph: dict[str, set[str]] = defaultdict(set)

    for module, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.level:
                    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
                    package_parts = package.split(".")
                    prefix = package_parts[: len(package_parts) - node.level + 1]
                    imported = [".".join([*prefix, node.module])]
                else:
                    imported = [node.module]
            else:
                imported = []

            for target in imported:
                if not target.startswith("scribe"):
                    continue
                while target and target not in modules:
                    target = target.rpartition(".")[0]
                if target and target != module:
                    graph[module].add(target)

    return {module: graph[module] for module in modules}


def _find_cycle(graph: dict[str, set[str]]) -> tuple[str, ...] | None:
    complete: set[str] = set()
    active: list[str] = []

    def visit(module: str) -> tuple[str, ...] | None:
        if module in active:
            start = active.index(module)
            return (*active[start:], module)
        if module in complete:
            return None

        active.append(module)
        for dependency in sorted(graph[module]):
            cycle = visit(dependency)
            if cycle:
                return cycle
        active.pop()
        complete.add(module)
        return None

    for module in sorted(graph):
        cycle = visit(module)
        if cycle:
            return cycle
    return None


def test_internal_source_dependencies_are_acyclic() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src"
    cycle = _find_cycle(_internal_dependency_graph(source_root))
    assert cycle is None, "Internal import cycle: " + " -> ".join(cycle or ())


def test_maintenance_cli_commands_remain_thin_delegators() -> None:
    """Keep system and media orchestration out of the central Typer entrypoint."""
    main_path = Path(__file__).resolve().parents[2] / "src" / "scribe" / "cli" / "main.py"
    tree = ast.parse(main_path.read_text(encoding="utf-8"), filename=str(main_path))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    expected_modules = {
        "info": "scribe.cli.system",
        "doctor": "scribe.cli.system",
        "health_check": "scribe.cli.system",
        "support_bundle": "scribe.cli.system",
        "clean": "scribe.cli.media",
    }

    for function_name, delegated_module in expected_modules.items():
        function = functions[function_name]
        imported_modules = {
            node.module
            for node in ast.walk(function)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert delegated_module in imported_modules
        assert function.end_lineno is not None
        assert function.end_lineno - function.lineno < 70
