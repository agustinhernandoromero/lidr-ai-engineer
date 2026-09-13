# Máster AI Engineering — LIDR

Repositorio del programa. Cada sesión se entrega en su propia rama; `main` contiene solo este índice.

## Proyecto

Servicio que recibe transcripciones de reuniones de requerimientos técnicos y devuelve estimaciones de software estructuradas generadas por LLM. Arranca con arquitectura **CAG** (contexto inyectado en el prompt del sistema) y evoluciona hacia **RAG** y agentes en los módulos posteriores.

## Organización del repositorio

- `main` — índice, documentación general y convenciones. No contiene código de sesiones.
- `sesion-NN-<tema>` — una rama por sesión con la entrega completa de esa sesión.

Cada entrega se revisa desde el enlace de su propia rama.

## Sesiones

| # | Tema | Rama | Estado |
|---|------|------|--------|
| 01 | — | — | Sin entrega |
| 02 | Estimador de software con arquitectura CAG (FastAPI) | [`sesion-02-cag`](../../tree/sesion-02-cag) | Entregada |
| 03 | — | — | Pendiente |

## Stack

Python 3.11+ · FastAPI · uv · Pydantic · pytest · GitHub Actions

## Convenciones

- **Ramas**: `sesion-NN-tema-en-kebab-case`, numeración a dos dígitos, sin acentos ni mayúsculas.
- Una sesión que continúa el proyecto parte de la rama de la sesión anterior; un ejercicio independiente parte de `main`.
- Una vez entregada y revisada, la rama de una sesión no se reescribe.
- Secretos siempre en `.env` (ignorado por Git); `.env.example` documenta las variables necesarias.
- CI en `.github/workflows/ci.yml` dentro de cada rama de sesión.

## Histórico

El repositorio [`Mi-proyecto-remoto-S1`](https://github.com/agustinhernandoromero/Mi-proyecto-remoto-S1) se conserva como backup de la primera versión de esta entrega.
