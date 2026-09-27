"""Guardas contra imports circulares en app/dependencies.py y app/services/.

``app.dependencies`` importa de ``app.services.cache`` y ``app.services.llm_service``
importa de vuelta ``app.dependencies``. Dentro de un mismo proceso de pytest esto no
se puede reproducir de forma fiable: en cuanto un test importa ``app.main`` (o
cualquier otra cosa que toque estos módulos), quedan cacheados en ``sys.modules``
y cualquier import posterior los reutiliza sin volver a ejecutar el ciclo.

Por eso cada caso aquí lanza un intérprete de Python nuevo y limpio, para
comprobar que el módulo indicado funciona como el PRIMER import del proceso,
sin depender del orden en que pytest recoja el resto de tests.
"""

import subprocess
import sys

import pytest

MODULES_THAT_MUST_IMPORT_STANDALONE = [
    "app.dependencies",
    "app.services.cache",
    "app.services.llm_service",
    "app.main",
]


@pytest.mark.parametrize("module", MODULES_THAT_MUST_IMPORT_STANDALONE)
def test_module_imports_as_first_import_in_a_fresh_process(module):
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
