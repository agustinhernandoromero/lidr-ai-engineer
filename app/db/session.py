"""Engine async de SQLAlchemy y dependencia FastAPI con una sesión por petición."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Engine compartido; se crea en la primera petición, no al importar."""
    # pool_pre_ping: descarta conexiones muertas (p. ej. tras reiniciar Postgres).
    return create_async_engine(get_settings().DATABASE_URL, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: los objetos siguen legibles (p. ej. document.id)
    # después del commit sin otra consulta.
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependencia FastAPI: una sesión por petición, cerrada al terminar."""
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    """Cierra el pool de conexiones al apagar la app."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
