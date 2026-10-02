"""Estado de las sesiones conversacionales del estimador.

Separa dos cosas que suelen mezclarse:

- **Historial** (``ConversationHistory``): los mensajes brutos user/assistant
  que viajan a la API en cada llamada. Se acota con una ventana deslizante de
  ``max_turns`` pares; el system prompt NO se guarda aquí, se regenera en cada
  turno a partir de la metadata.
- **Memoria** (``ProjectMetadata``): los hechos del proyecto en curso (nombre,
  equipo, tecnologías, alcance). Sobrevive aunque el turno que los mencionó ya
  haya salido de la ventana, porque se inyecta en el system prompt.

Todo vive en un diccionario en memoria del proceso. Aceptamos esa volatilidad
en esta fase: es un prototipo de un único proceso y perder las sesiones al
reiniciar no rompe nada (el cliente crea una nueva). Con varios workers de
uvicorn cada uno tendría su propio diccionario; el paso natural sería Redis,
que ya usamos para la caché.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class ProjectMetadata(BaseModel):
    """Hechos conocidos del proyecto en curso."""

    project_name: Optional[str] = None
    assumed_team_size: Optional[int] = Field(default=None, ge=1, le=500)
    mentioned_technologies: list[str] = Field(default_factory=list)
    agreed_scope: Optional[str] = None

    def is_empty(self) -> bool:
        return not (
            self.project_name
            or self.assumed_team_size
            or self.mentioned_technologies
            or self.agreed_scope
        )

    def merge(self, new: "ProjectMetadata") -> "ProjectMetadata":
        """Fusiona los hechos de un turno nuevo sobre los conocidos.

        Un valor nuevo no vacío sustituye al anterior; un ``None`` o cadena
        vacía no borra nada (el extractor puede no mencionar el nombre del
        proyecto en el turno 3 y eso no significa que haya cambiado). Las
        tecnologías se acumulan sin duplicados, ignorando mayúsculas.
        """
        technologies = list(self.mentioned_technologies)
        seen = {t.lower() for t in technologies}
        for tech in new.mentioned_technologies:
            tech = tech.strip()
            if tech and tech.lower() not in seen:
                technologies.append(tech)
                seen.add(tech.lower())

        return ProjectMetadata(
            project_name=new.project_name or self.project_name,
            assumed_team_size=new.assumed_team_size or self.assumed_team_size,
            mentioned_technologies=technologies,
            agreed_scope=new.agreed_scope or self.agreed_scope,
        )


class ConversationHistory:
    """Historial user/assistant con ventana deslizante de ``max_turns`` pares."""

    def __init__(self, max_turns: int) -> None:
        if max_turns < 1:
            raise ValueError("max_turns debe ser al menos 1")
        self.max_turns = max_turns
        self._turns: list[tuple[str, str]] = []

    def __len__(self) -> int:
        return len(self._turns)

    def add_turn(self, user: str, assistant: str) -> None:
        """Añade un par y descarta los más antiguos si se supera la ventana."""
        self._turns.append((user, assistant))
        if len(self._turns) > self.max_turns:
            self._turns = self._turns[-self.max_turns :]

    def to_messages_list(self, system_prompt: str) -> list[dict[str, str]]:
        """Array ``messages`` neutral (``{"role", "content"}``) listo para el wrapper.

        El system prompt va siempre primero y se pasa en cada llamada, de modo
        que refleja la metadata actual y nunca sale de la ventana.
        """
        messages = [{"role": "system", "content": system_prompt}]
        for user, assistant in self._turns:
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": assistant})
        return messages

    def as_dicts(self) -> list[dict[str, str]]:
        return [{"user": u, "assistant": a} for u, a in self._turns]


@dataclass
class Session:
    session_id: str
    history: ConversationHistory
    metadata: ProjectMetadata = field(default_factory=ProjectMetadata)
    turn_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Serializa los turnos de una misma sesión: dos peticiones simultáneas
    # (p. ej. doble clic) no deben intercalar su lectura/escritura del historial.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class SessionStore:
    """Sesiones indexadas por ``session_id`` en memoria del proceso."""

    def __init__(self, max_turns: int) -> None:
        self.max_turns = max_turns
        self._sessions: dict[str, Session] = {}

    def __len__(self) -> int:
        return len(self._sessions)

    def create(self) -> Session:
        session_id = str(uuid.uuid4())
        session = Session(session_id=session_id, history=ConversationHistory(self.max_turns))
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)
