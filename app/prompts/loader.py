"""Carga y renderizado de prompts versionados con Jinja2.

Cada versión vive en su propio directorio (``estimation/v1/``, ``estimation/v2/``…),
de forma que cambiar de versión no obliga a tocar el resto del código: basta con
pasar ``version="v2"`` a :func:`render_estimation_prompt`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import structlog
from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from app.schemas import EstimationRequest

PROMPTS_DIR = Path(__file__).parent
DEFAULT_VERSION = "v1"

logger = structlog.get_logger(__name__)

# StrictUndefined hace que una variable no pasada al contexto reviente en el
# render en vez de silenciarse como cadena vacía: los errores de plantilla
# aparecen en los tests, no en producción.
_env = Environment(
    loader=FileSystemLoader(PROMPTS_DIR),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def _fingerprint(text: str) -> str:
    """Hash corto del contenido renderizado, para correlacionar en logs."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def available_versions() -> list[str]:
    """Versiones de prompt presentes en disco, ordenadas."""
    base = PROMPTS_DIR / "estimation"
    return sorted(p.name for p in base.iterdir() if p.is_dir() and p.name.startswith("v"))


def render_estimation_prompt(
    request: EstimationRequest,
    version: str = DEFAULT_VERSION,
) -> tuple[str, str]:
    """Renderiza el par (system, user) para una petición de estimación.

    Args:
        request: petición ya validada por Pydantic.
        version: subdirectorio de ``prompts/estimation/`` a usar.

    Returns:
        Tupla ``(system, user)`` lista para enviar al modelo como dos mensajes.

    Raises:
        ValueError: si la versión solicitada no existe en disco.
    """
    context = {
        "description": request.description,
        "project_type": request.project_type.value,
        "detail_level": request.detail_level.value,
        "output_format": request.output_format.value,
        "reference_projects": [rp.model_dump() for rp in (request.reference_projects or [])],
    }

    try:
        system = _env.get_template(f"estimation/{version}/system.j2").render(**context)
        user = _env.get_template(f"estimation/{version}/user.j2").render(**context)
    except TemplateNotFound as exc:
        raise ValueError(
            f"Versión de prompt desconocida: '{version}'. "
            f"Disponibles: {', '.join(available_versions())}"
        ) from exc

    logger.info(
        "prompt_rendered",
        prompt_version=version,
        project_type=context["project_type"],
        detail_level=context["detail_level"],
        output_format=context["output_format"],
        reference_projects=len(context["reference_projects"]),
        system_hash=_fingerprint(system),
        user_hash=_fingerprint(user),
        system_chars=len(system),
        user_chars=len(user),
    )

    return system, user
