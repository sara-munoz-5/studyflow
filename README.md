# StudyFlow AI

Asistente académico local para registrar materias y actividades, generar planes de estudio, aprobar sus sesiones y exportarlas a un calendario. Streamlit se comunica con FastAPI por HTTP. PostgreSQL conserva los datos y el agente ejecuta LangGraph dentro del backend.

## Ejecutar con Docker Compose

Si ya tienes un archivo `.env` y un volumen PostgreSQL, conserva las credenciales de esa instalación. Para una instalación nueva, copia la plantilla y elige una contraseña local antes del primer arranque.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose up -d --build --wait
docker compose exec -T ollama ollama pull qwen3:4b-instruct
docker compose exec -T ollama ollama list
docker compose ps
```

Si cambias `OLLAMA_MODEL` en `.env`, usa ese mismo nombre en el comando `ollama pull`. La primera inferencia en CPU puede tardar varios minutos por la carga del modelo. El backend permite hasta 600 segundos de espera por solicitud de inferencia mediante `OLLAMA_TIMEOUT_SECONDS`. El modelo predeterminado es [Qwen3 4B Instruct](https://ollama.com/library/qwen3%3A4b-instruct). El modelo se conserva en el volumen `ollama_data`. Alembic se ejecuta antes de iniciar FastAPI y adopta la tabla `subjects` del prototipo.

| Servicio | Dirección |
| --- | --- |
| Streamlit | http://127.0.0.1:8501 |
| Documentación REST | http://127.0.0.1:8001/docs |
| Salud de PostgreSQL | http://127.0.0.1:8001/health/db |

Para iniciar el modo determinista mientras se descarga Ollama, ejecuta `docker compose up -d --build --wait backend frontend`.

## Probar el flujo

1. En **Mi disponibilidad**, registra compromisos únicos o semanales, como transporte de 17:00 a 18:00.
2. En **Mis materias**, crea o abre una materia y registra una actividad. Agrega filas con cada tema, su prioridad y, si lo conoces, su nivel de dominio. Las horas estimadas se pueden omitir.
3. Pulsa **Generar plan** dentro de una actividad. Elige días y horario diario. Marca los bloques ocupados en la cuadrícula y selecciona **Agente con Ollama** o **Planificador sin IA**.
4. Revisa los objetivos, las estimaciones por tema y las sesiones agrupadas por día. Puedes aceptar el borrador o pulsar **Modificar o regenerar** para ajustar el esfuerzo sugerido.
5. Consulta **Planes de estudio** dentro de la materia para recuperar el historial. En **Mi calendario**, alterna día, semana y mes. Selecciona un evento para abrir sus detalles.
6. En un plan aprobado o desde una sesión del calendario, registra minutos efectivos y consulta el historial de seguimiento. Pulsa **Replanificar tiempo restante** para solicitar otro horario o proponer un nuevo plazo. Aceptar el reemplazo actualiza las reservas.
7. Descarga el archivo `.ics` de un plan aprobado e impórtalo en Google Calendar, Outlook u otra aplicación compatible.

```powershell
docker compose logs -f backend
docker compose restart backend frontend
```

Los registros de ejecuciones agénticas incluyen el identificador de ejecución, la actividad y los pasos realmente ejecutados, su duración y su resultado. Las migraciones `0002_plan_history` y `0003_study_tracking` añaden cobertura, plazos de día completo, temas estructurados, estimaciones y seguimiento. La revisión `0004_personal_schedule` añade los compromisos personales, la relación entre regeneraciones y el identificador persistente de generación. Los identificadores de temas se conservan al editarlos en la tabla. En el historial anterior, una fecha o cuota que no se haya registrado se muestra como desconocida. Los cambios se conservan al reiniciar. Los horarios externos se indican como bloques ocupados y la exportación se realiza mediante importación manual del archivo.

## Pruebas

```powershell
python -m pip install -r backend/requirements-dev.txt -r frontend/requirements.txt -r frontend/requirements-calendar.txt
python -m pytest -q frontend/test_frontend.py

# Pruebas REST y migraciones con SQLite. El flujo LangGraph usa un doble de modelo.
docker compose exec -T backend python -m pytest -q

# Las mismas pruebas con PostgreSQL. Cada prueba crea y elimina su propio esquema temporal.
docker compose exec -T -e STUDYFLOW_TEST_POSTGRES=1 backend python -m pytest -q

# Prueba de integración con Ollama después de descargar el modelo.
docker compose exec -T -e STUDYFLOW_TEST_POSTGRES=1 -e STUDYFLOW_TEST_OLLAMA=1 backend python -m pytest -q
```

La prueba integral requiere Playwright y una instancia de prueba vacía. Desde la raíz del repositorio:

```powershell
python -m pip install playwright
python -m playwright install chromium
docker compose build backend frontend
docker compose run --rm -d --no-deps --name studyflow-test-api -p 127.0.0.1:18001:8000 -e DATABASE_URL=sqlite:////tmp/studyflow-e2e.db backend
docker compose run --rm -d --no-deps --name studyflow-test-ui -p 127.0.0.1:18501:8501 -e STUDYFLOW_API_URL=http://studyflow-test-api:8000 frontend
python frontend/e2e_studyflow.py --api http://127.0.0.1:18001 --ui http://127.0.0.1:18501
docker stop studyflow-test-ui studyflow-test-api
```

En Windows, puedes indicar un Edge instalado mediante `STUDYFLOW_TEST_CHROMIUM` y omitir la descarga de Chromium. Los dos contenedores temporales usan una base SQLite propia.

Para ejecutar la API fuera de Docker con Python 3.12, instala `backend/requirements-dev.txt`, configura `DATABASE_URL` con una instancia PostgreSQL accesible y ejecuta `alembic upgrade head` seguido de `uvicorn app.main:app --port 8001` desde `backend/`. Configura `OLLAMA_BASE_URL` si Ollama escucha en una dirección distinta de `http://localhost:11434`.

Consulta el [diseño técnico y los contratos](docs/design/studyflow.md).
