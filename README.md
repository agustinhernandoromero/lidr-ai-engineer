# 🚀 Sesion 02: Estimador de Software con Arquitectura CAG (FastAPI)

Este es el inicio del proyecto que ejecutaremos a lo largo del programa.

La arquitectura inicial es CAG: todo el contexto que necesita el modelo viaja en cada llamada — no hay base de datos, no hay recuperación, no hay persistencia.


---

## 💡 ¿Por qué Arquitectura CAG (Context-Augmented Generation)?

¿Por qué CAG? Porque los datos de referencia (unas pocas estimaciones de ejemplo) caben perfectamente en la ventana de contexto del modelo. No necesitamos infraestructura adicional. Esta simplicidad nos permite centrarnos en la lógica de negocio y en la calidad del rápido antes de evolucionar hacia RAG en módulos posteriores.

En esta etapa inicial del proyecto, los datos históricos de referencia (estimaciones previas, estándares de horas y roles) son un conjunto acotado y de alta calidad que cabe holgadamente en la ventana de contexto de los modelos modernos (`claude-haiku-4-5`).

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
- Clave de API de  **Anthropic** (`ANTHROPIC_API_KEY`).

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
LLM_PROVIDER=anthropic 

# Configuración Anthropic (opcional si usas Claude)
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5-20251001

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

#### Usando el archivo incluido:

```bash
curl -X POST http://localhost:8000/api/v1/estimate \
  -H "Content-Type: application/json" \
  -d @data/sample_transcription.json
```

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

