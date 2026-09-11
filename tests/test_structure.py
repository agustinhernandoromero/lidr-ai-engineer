"""Automated test validating directory structure and project scaffolding requirements."""

from pathlib import Path


def test_directory_structure():
    """Verify that all required folders and files exist according to the CAG project spec."""
    project_root = Path(__file__).resolve().parent.parent

    expected_paths = [
        "app/__init__.py",
        "app/main.py",
        "app/config.py",
        "app/routers/__init__.py",
        "app/routers/estimations.py",
        "app/services/__init__.py",
        "app/services/llm_service.py",
        "app/context/__init__.py",
        "app/context/examples.py",
        ".env.example",
        ".gitignore",
        "pyproject.toml",
        "README.md",
    ]

    for rel_path in expected_paths:
        full_path = project_root / rel_path
        assert full_path.exists(), f"Falta el archivo o directorio requerido: {rel_path}"


def test_gitignore_contains_env():
    """Verify that .env is explicitly excluded in .gitignore."""
    project_root = Path(__file__).resolve().parent.parent
    gitignore_path = project_root / ".gitignore"
    assert gitignore_path.exists(), ".gitignore no existe"

    content = gitignore_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines()]
    assert ".env" in lines or any(".env" in line for line in lines), ".env debe estar en .gitignore"


def test_examples_context_structure():
    """Verify that context examples contain at least 2 structured examples."""
    from app.context.examples import ESTIMATION_EXAMPLES

    assert isinstance(ESTIMATION_EXAMPLES, list), "ESTIMATION_EXAMPLES debe ser una lista"
    assert len(ESTIMATION_EXAMPLES) >= 2, "Debe haber al menos 2 ejemplos de contexto estático"

    for idx, example in enumerate(ESTIMATION_EXAMPLES):
        assert "meeting_summary" in example, f"Ejemplo {idx} debe contener 'meeting_summary'"
        assert "estimation" in example, f"Ejemplo {idx} debe contener 'estimation'"
        assert len(example["meeting_summary"]) > 20, f"Resumen del ejemplo {idx} demasiado corto"
        assert len(example["estimation"]) > 50, f"Estimación del ejemplo {idx} demasiado corta"
