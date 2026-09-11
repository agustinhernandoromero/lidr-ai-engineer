# 🚀 Proyecto 1: Estimador de Software con Arquitectura CAG (FastAPI)

Servicio backend en **FastAPI** que procesa transcripciones de reuniones de requerimientos técnicos y genera estimaciones de proyectos de software estructuradas mediante Modelos de Lenguaje (LLMs) aplicando **CAG (Context-Augmented Generation)**.

---

## 💡 ¿Por qué Arquitectura CAG (Context-Augmented Generation)?

En esta etapa inicial del proyecto, los datos históricos de referencia (estimaciones previas, estándares de horas y roles) son un conjunto acotado y de alta calidad que cabe holgadamente en la ventana de contexto de los modelos modernos (`gpt-4o-mini`, `claude-3-5-haiku`).

- **Sin base de datos ni indexación vectorial innecesaria**: Todo el contexto necesario viaja directamente inyectado en el prompt de sistema.
- **Simplicidad operativa y determinismo**: Permite iterar velozmente en el prompt engineering y la calidad de las respuestas antes de evolucionar a arquitecturas RAG en módulos posteriores.

---

## 📁 Estructura del Proyecto

```text
estimador-cag/
├── .github/
│   └── workflows/
│       └── ci.yml                 # Pipeline CI automatizado para GitHub Actions
├── app/
│   ├── __init__.py
│   ├── main.py                    # Configuración e instanciación de FastAPI
│   ├── config.py                  # Pydantic BaseSettings (.env loading)
│   ├── routers/
│   │   ├── __init__.py
│   │   └── estimations.py         # Router POST /api/v1/estimate
│   ├── services/
│   │   ├── __init__.py
│   │   └── llm_service.py         # Lógica CAG y llamadas a OpenAI/Anthropic
│   └── context/
│       ├── __init__.py
│       └── examples.py            # Ejemplos estáticos de estimaciones inyectados en prompt
├── data/
│   ├── sample_transcription.json  # Payload de ejemplo para pruebas rápidas
│   └── transcription_meeting.txt  # Transcripción textual de reunión de prueba
├── tests/
│   ├── __init__.py
│   ├── test_structure.py          # Validación automatizada de estructura y archivos
│   └── test_api.py                # Tests unitarios y de integración con mocks
├── .env.example                   # Plantilla de variables de entorno requeridas
├── .env                           # Variables de entorno locales (en .gitignore)
├── .gitignore                     # Exclusiones de Git (incluye .env)
├── pyproject.toml                 # Dependencias y configuración con uv / hatchling
└── README.md                      # Documentación completa del proyecto
```

---

## 🛠️ Requisitos Previos

- **Python 3.11+**
- **uv** como gestor de paquetes moderno y ultrarrápido ([Instalación de uv](https://docs.astral.sh/uv/getting-started/installation/))
- Clave de API de **OpenAI** (`OPENAI_API_KEY`) y/o **Anthropic** (`ANTHROPIC_API_KEY`).

---

## ⚙️ Instalación y Configuración

### 1. Clonar el repositorio y sincronizar dependencias con `uv`

```bash
# Sincronizar el entorno virtual con todas las dependencias
uv sync --extra dev
```

### 2. Configurar variables de entorno

Copia el archivo `.env.example` a `.env` y añade tus claves de API:

```bash
cp .env.example .env
```

Edita `.env`:

```ini
# Proveedor activo: 'openai' o 'anthropic'
LLM_PROVIDER=openai

# Configuración OpenAI (por defecto gpt-4o-mini)
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# Configuración Anthropic (opcional si usas Claude)
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-3-5-haiku-20241022

# Configuración de la App
APP_NAME="CAG Software Estimator API"
APP_ENV=development
PORT=8000
HOST=0.0.0.0
```

---

## 🚀 Ejecución del Servidor

Inicia el servidor en modo desarrollo con recarga automática:

```bash
uv run uvicorn app.main:app --reload
```

El servicio estará disponible en:
- **API Base**: `http://localhost:8000`
- **Health Check**: `http://localhost:8000/health`
- **Documentación Interactiva (Swagger UI)**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

---

## 📡 Endpoints y Ejemplos de Uso

### 1. Health Check (`GET /health`)

```bash
curl -X GET http://localhost:8000/health
```

**Respuesta:**
```json
{
  "status": "ok",
  "app_name": "CAG Software Estimator API",
  "environment": "development",
  "provider": "openai"
}
```

---

### 2. Generar Estimación (`POST /api/v1/estimate`)

#### Usando `curl`:

```bash
curl -X POST http://localhost:8000/api/v1/estimate \
  -H "Content-Type: application/json" \
  -d '{
    "transcription": "En la reunión con el equipo de marketing, el cliente explicó que necesita una landing page con formulario de contacto, integración con su CRM actual (HubSpot), y una sección de blog con editor WYSIWYG. El plazo ideal sería tenerlo listo en 4 semanas. El diseño ya existe en Figma."
  }'
```

#### Usando el archivo de ejemplo incluido:

```bash
curl -X POST http://localhost:8000/api/v1/estimate \
  -H "Content-Type: application/json" \
  -d @data/sample_transcription.json
```

**Ejemplo de Respuesta JSON:**

```json
{
  "estimation": "## Estimación: Landing Page y Blog con Integración HubSpot\n\n### 1. Resumen Ejecutivo\nDesarrollo de landing page de alta conversión integrada con HubSpot CRM y blog autogestionable...\n\n### 2. Desglose de Tareas y Horas:\n1. **Frontend Landing & Blog**: 35 horas\n2. **Integración HubSpot API**: 15 horas\n3. **Módulo Blog & WYSIWYG**: 20 horas\n4. **QA y Despliegue**: 10 horas\n\n**Total estimado**: 80 horas\n**Equipo recomendado**: 1 Desarrollador Full-stack Senior + 1 QA\n**Duración estimada**: 3 - 4 semanas",
  "model": "gpt-4o-mini",
  "provider": "openai",
  "created_at": "2026-09-12T00:00:00.000000+00:00"
}
```

---

## 🧪 Pipeline Automatizado y Pruebas

El repositorio incluye validación automatizada de estructura y pruebas unitarias/integración:

### Ejecutar tests localmente:

```bash
uv run pytest -v
```

### Pipeline de Integración Continua (CI):
El archivo `.github/workflows/ci.yml` ejecuta automáticamente en cada push o pull request:
1. Instalación de entorno limpio con `uv`.
2. Verificación de que `.env` no esté expuesto ni trackeado en Git.
3. Validación de estructura de directorios según especificación.
4. Pruebas de endpoints FastAPI (con mocks de LLM para correr sin consumir créditos en CI).

---

## ✅ Lista de Verificación del Ejercicio

- [x] Proyecto inicializado y configurable con `uv`.
- [x] Estructura modular (`routers/`, `services/`, `context/`).
- [x] Gestión segura de configuración vía `pydantic-settings` y `.env`.
- [x] Contexto estático enriquecido en `context/examples.py`.
- [x] Servicio LLM con arquitectura CAG soportando OpenAI y Anthropic.
- [x] Endpoint `POST /api/v1/estimate` con validaciones de schemas Pydantic.
- [x] Endpoint `GET /health` y documentación OpenAPI/Swagger en `/docs`.
- [x] `.env` incluido en `.gitignore` y archivo `.env.example` documentado.
- [x] Pipeline CI automatizado y tests en `tests/`.
- [x] Archivos de transcripción de ejemplo en `data/`.
