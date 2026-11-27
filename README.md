# StudyFlow AI

Asistente académico local para registrar materias y actividades, generar planes de estudio, aprobar sus sesiones y exportarlas a un calendario. Streamlit se comunica con FastAPI por HTTP. PostgreSQL conserva los datos y el agente ejecuta LangGraph dentro del backend.

Las fechas límite, la disponibilidad y el avance suelen quedar repartidos entre listas y calendarios. StudyFlow AI reúne esos datos para convertir la carga académica en sesiones factibles, hacer visible el esfuerzo que queda sin cubrir y ajustar el plan a medida que el estudiante avanza. Cada propuesta queda sujeta a aprobación humana.

## Arquitectura y estructura

El backend es un monolito modular. FastAPI ejecuta los módulos académicos, de planificación, agentes y calendario en un mismo proceso. La arquitectura hexagonal mantiene las reglas en el dominio, coordina los casos de uso en la capa de aplicación y conecta los puertos con adaptadores REST, SQLAlchemy, Ollama e iCalendar. Streamlit actúa como cliente HTTP.

| Ruta | Contenido |
| --- | --- |
| `backend/app/academic/` | Dominio, casos de uso y adaptadores de materias y actividades. |
| `backend/app/planning/` | Planificador, borradores, reservas, aprobación y seguimiento. |
| `backend/app/agents/` | Grafo de LangGraph y conexión con ChatOllama. |
| `backend/app/calendar/` | Compromisos personales, recurrencias y exportación iCalendar. |
| `backend/app/core/` | Conexión a PostgreSQL y telemetría. |
| `backend/migrations/`, `backend/tests/` | Migraciones Alembic y pruebas de API e integración. |
| `frontend/` | Interfaz Streamlit, FullCalendar y pruebas de interfaz. |
| `docker-compose.yml`, `.env.example` | Servicios y plantilla de configuración local. |

## Tecnologías

Python 3.12 en Docker, FastAPI, Pydantic, SQLAlchemy 2, Psycopg 3, PostgreSQL 17, Alembic, LangGraph, Ollama con Qwen3, Streamlit, FullCalendar, iCalendar, Pytest y Playwright.

## Ejecutar con Docker Compose

Instala Docker Desktop o Docker Engine con Compose v2. Para pruebas y ejecución fuera de Docker, usa Python 3.12.

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

Los servicios de Compose comparten una red interna. Streamlit ofrece una cuadrícula de disponibilidad de 30 minutos en Bogotá y usa FullCalendar, mediante `streamlit-calendar` 1.5.0, para mostrar vistas diaria, semanal y mensual.

## Modelo PostgreSQL

| Tabla | Contenido |
| --- | --- |
| `subjects` | Identificador, nombre, código único y descripción opcional. |
| `activities` | FK a materia, título, tipo, fecha límite, dificultad, temas, horas estimadas, estado, prioridad, día límite opcional y pesos relativos por tema. |
| `study_plans` | FK a actividad, modo, estado, zona IANA, ventanas disponibles y ocupadas, límite de sesión, minutos faltantes, razones, herramientas ejecutadas, fecha de creación y una instantánea de cobertura. |
| `study_sessions` | FK a plan, tema, objetivo, inicio y fin con zona y estado. La duración se calcula en minutos a partir de los extremos. |
| `personal_blocks` | Compromisos únicos y series semanales que bloquean ventanas de estudio. |

Los tipos de actividad son `exam`, `laboratory`, `assignment` y `project`. Los estados son `pending`, `completed` y `cancelled`. El campo adicional `priority` usa una escala de 1 a 5 con valor inicial 3. Las prioridades 3 a 5 aprovechan los primeros minutos posibles y las prioridades 1 y 2 dejan hasta 30 minutos libres al inicio cuando hay holgura. El generador trabaja sobre una actividad a la vez.

Una materia con actividades y una actividad con planes se protegen con claves foráneas restrictivas. Una actualización de plazo o temas devuelve 409 si invalidaría sesiones futuras aprobadas. La migración inicial conserva la tabla de materias si ya existe y crea las tablas nuevas. La base de datos y los archivos del modelo usan volúmenes persistentes independientes.

## Contrato REST

| Método y ruta | Resultado |
| --- | --- |
| `POST /subjects`, `POST /activities` | Crea un registro y devuelve 201. |
| `GET /subjects`, `GET /activities` | Lista los registros. |
| `GET /subjects/{id}`, `GET /activities/{id}` | Lee un registro. |
| `PUT /subjects/{id}`, `PUT /activities/{id}` | Reemplaza los campos editables del registro. |
| `DELETE /subjects/{id}`, `DELETE /activities/{id}` | Devuelve 204 tras eliminar. |
| `POST /plans` | Genera un borrador (201) o informa que no hay minutos disponibles (200 y `status=unavailable`). |
| `GET /plans`, `GET /plans/{id}` | Lista planes o consulta el detalle con sesiones. |
| `POST /plans/{id}/approve` | Revalida y aprueba. Repetir la aprobación devuelve el mismo plan aprobado. |
| `GET /plans/{id}/calendar.ics` | Descarga las sesiones aprobadas e incluye la materia y la zona de presentación del plan. |
| `GET /plans/progress/{uuid}` | Consulta las etapas observadas cuando la generación incluyó la cabecera opcional `X-Plan-Progress`. |

`POST /plans` recibe `activity_id`, `timezone` (IANA), `availability` y `busy` (listas de objetos con `start` y `end`), `max_session_minutes` y `mode`. El modo predeterminado es `agent` y el alternativo es `deterministic`. Las fechas REST son ISO 8601 con offset. Las comparaciones se normalizan a UTC. El archivo iCalendar también se escribe en UTC y el cliente de calendario aplica la zona de visualización. Una propuesta parcial devuelve `missing_minutes` y `reasons`. Un resultado sin sesiones devuelve 200. Si incluye una estimación nueva, se guarda como `unavailable` para consultar el esfuerzo sin reservar tiempo.

El contrato usa 404 para recursos inexistentes, 409 para duplicados, relaciones protegidas o conflictos de calendario, 422 para entradas inválidas, 502 para un flujo agéntico incompleto y 503 cuando Ollama o el modelo no están disponibles. FastAPI publica los esquemas en `/docs` y `/openapi.json`.

La revisión aditiva `0002_plan_history` conserva las fechas, estados y sesiones existentes. Los planes previos mantienen creación y cuotas originales como desconocidas. Para consultar su cobertura se combinan los temas actuales con los temas históricos de sus sesiones. Los planes nuevos almacenan la instantánea original de cada tema y su cuota.

`/activities` conserva `topics` como lista de texto y añade `topic_ids` en la respuesta. Las actividades antiguas derivan un UUID del nombre y la actividad. Las filas estructuradas persisten su UUID y lo conservan al editar desde la tabla. `topic_weights` acepta pesos de 1 a 5 por nombre exacto. Un `due_day` explícito representa un plazo de día completo en Bogotá y fija el límite exclusivo en la medianoche siguiente. Los clientes que envían `due_date` mantienen sus horarios.

`/plans` añade `created_at`, `coverage`, `required_minutes`, `planned_minutes` y la configuración de disponibilidad del borrador a sus respuestas. `tools_used` conserva su contrato. El progreso usa eventos reales de las etapas del backend. Su almacenamiento es temporal y está en memoria del único proceso FastAPI de Compose.

## Estimación, seguimiento y reemplazos

La revisión `0003_study_tracking` añade JSON de temas estructurados en actividades, datos de estimación y reemplazo en planes e historial de seguimiento en sesiones. Las horas estimadas pasan a ser opcionales. Las filas antiguas se leen con sus nombres y UUID anteriores. Una edición con `topic_details` conserva el ID presentado y permite cambiar nombre, prioridad y dominio. Se siguen admitiendo los clientes que envían `topics` como lista de nombres. Los UUID de una fila nueva se crean en el servidor.

| Operación | Contrato adicional |
| --- | --- |
| Crear o editar actividad | `topic_details` contiene `id` opcional, `name`, `priority` de 1 a 5 y `mastery` opcional de 1 a 5. `estimated_hours` admite omisión o valor nulo. |
| Generar borrador | `target_minutes` ajusta el esfuerzo de una propuesta inicial. `replaces_plan_id` genera una alternativa con el esfuerzo restante y `proposed_due_date` permite proponer un cambio de plazo. |
| Consultar plan | `coverage` incluye minutos sugeridos, justificación breve y prioridad declarada. `estimate_source`, `assumptions` y `completed_minutes` permiten interpretar el esfuerzo y avance. |
| Registrar avance | `PATCH /plans/{id}/sessions/{session_id}/tracking` recibe `status` con `pending`, `completed`, `partial` o `not_done` y `effective_minutes` cuando corresponda. |

El esquema del agente exige una sugerencia de 5 a 480 minutos y una justificación por tema al estimar una actividad sin horas. LangGraph procesa lotes de hasta 12 temas y el servicio conserva la suma aunque el tiempo libre sea menor. Los supuestos de dominio intermedio se muestran cuando falta ese dato. El modo determinista calcula una referencia mediante dificultad y dominio. Las horas manuales heredadas y los ajustes del estudiante se distinguen de la estimación de Ollama.

El avance queda separado del estado de reserva de la sesión. Completar suma su duración, avanzar parcialmente suma los minutos explícitos y los demás estados registran cero minutos. Cada actualización añade al historial su fecha y el cambio de estado. La replanificación resta los minutos efectivos del plan reemplazado y mantiene sus sesiones y datos históricos. Si una ventana de disponibilidad ya empezó al generar, se dejan cinco minutos para revisar el borrador. La aprobación comprueba la versión del plan de origen, revalida todas las reservas y aplica el nuevo plazo y el intercambio de reservas en la misma transacción. Después de aceptarlo, el plan anterior queda `superseded` y el vigente queda `approved`. El calendario conserva las sesiones completadas del historial y omite los bloques reemplazados.

## Planificador e IA agéntica con LangGraph

El servicio recupera actividad y materia, combina los bloques ocupados indicados por el estudiante con sesiones aprobadas y calcula las ventanas libres antes del plazo. Distribuye el esfuerzo entre todos los temas. Usa pesos declarados cuando existen y la prioridad propuesta por Ollama como señal relativa para los demás temas del modo agente. El modo determinista da el mismo peso a los temas sin esfuerzo declarado. La dificultad limita la duración de cada bloque. El diagnóstico de déficits distingue el plazo, el tiempo transcurrido, los bloqueos manuales y las reservas de planes aprobados. Los borradores son propuestas alternativas y la aprobación comprueba otra vez los solapamientos con los planes ya aprobados.

El flujo agéntico consulta datos de la aplicación, pide una propuesta pedagógica al modelo y la somete a reglas de planificación y revisión humana. En modo agente, LangGraph ejecuta la consulta académica y de disponibilidad antes de solicitar una propuesta a Ollama. El modelo recibe el contexto y un esquema JSON con una clave obligatoria por identificador de tema. Devuelve un objetivo comprobable y una prioridad pedagógica de 1 a 5 para cada tema. Pydantic comprueba el formato. El planificador ordena por prioridad pedagógica y conserva el orden de los temas de origen en caso de empate. El grafo ejecuta las siguientes operaciones deterministas.

| Paso del grafo | Operación |
| --- | --- |
| `get_activity_details` | Lee materia, temas, dificultad, esfuerzo, prioridad y plazo de la actividad seleccionada. |
| `get_available_slots` | Consulta las ventanas libres y el límite de cada sesión. |
| `estimate_study_sessions` | Ejecuta el planificador determinista con los objetivos aprobados por el esquema. |
| `validate_study_plan` | Comprueba fechas, duración y disponibilidad del último cálculo. |

El grafo admite un reintento para corregir una propuesta inválida y tiene un límite de diez pasos. Cada operación determinista del grafo queda en `tools_used`. Antes de guardar, la capa de aplicación recalcula y valida las sesiones con las ventanas vigentes bajo el bloqueo transaccional. Si hay una infracción, descarta la propuesta. La aprobación humana es una operación REST independiente.

Los logs emiten un objeto JSON por etapa con identificador de ejecución, identificador de actividad, etapa, duración, resultado y clase de error cuando corresponde. Los datos académicos, las respuestas del modelo y el texto de las excepciones quedan fuera de estos registros.

## Compromisos personales y calendario

La revisión aditiva `0004_personal_schedule` crea `personal_blocks` y añade identidad de solicitud y origen de regeneración a los planes. Los planes anteriores no reciben fechas ni relaciones inferidas.

| Método y ruta | Contrato |
| --- | --- |
| `GET /personal-blocks`, `GET /personal-blocks/{id}` | Lista y consulta compromisos. |
| `POST /personal-blocks`, `PUT /personal-blocks/{id}`, `DELETE /personal-blocks/{id}` | Crea, actualiza y elimina un compromiso o una serie. Una escritura que pisa una reserva devuelve 409 y mantiene la reserva. |
| `GET /personal-blocks/occurrences?start=YYYY-MM-DD&end=YYYY-MM-DD` | Expande ocurrencias en Bogotá para un rango de días con fin exclusivo, de hasta 366 días. |

Un compromiso guarda `day`, `start_time`, `end_time`, título, categoría y descripción opcionales, y `weekdays` con lunes igual a 0 y domingo igual a 6. Una lista vacía identifica un bloque único. Una lista con días identifica una recurrencia semanal desde `day` hasta `until` inclusive, o indefinida si se omite ese fin. PostgreSQL guarda una fila por serie. La expansión usa el intervalo solicitado y devuelve los extremos con offset.

El planificador convierte las ocurrencias pertinentes a UTC y las combina con los bloqueos manuales y las reservas aprobadas. La generación final y la aprobación consultan compromisos vigentes bajo el mismo bloqueo transaccional que protege la creación, edición y eliminación de compromisos. Ante un cruce, la API explica la reserva y propone una franja alternativa cuando encuentra una el mismo día. Las sesiones aprobadas se conservan.

El calendario usa un selector de vista y fecha de Streamlit para consultar exactamente las ocurrencias que muestra FullCalendar. El componente recibe la hora civil de Bogotá de forma explícita, con independencia de la zona del navegador. Filtrar materias afecta actividades y sesiones. Los compromisos personales tienen su propio filtro. Aceptar un borrador enfoca la siguiente sesión y deja disponible una acción directa hacia el calendario.

`POST /plans` conserva la cabecera opcional `X-Plan-Progress` y la usa también como identidad de la generación. Repetir la misma solicitud con una identidad guardada devuelve el plan existente y 200. Cambiar los parámetros con esa identidad o repetirla durante una generación activa devuelve 409. PostgreSQL protege la unicidad incluso entre procesos. `derived_from_plan_id` registra una regeneración. `replaces_plan_id` conserva el significado de reemplazo de reservas al aprobar.

## Configuración

| Variable | Uso |
| --- | --- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Configuración de PostgreSQL y del backend con Compose. |
| `POSTGRES_HOST` | Host para la conexión implícita del backend. El valor predeterminado es `db`. |
| `DATABASE_URL` | URL SQLAlchemy opcional que sustituye los parámetros anteriores. |
| `OLLAMA_BASE_URL` | URL de Ollama. Compose usa `http://ollama:11434`. |
| `OLLAMA_MODEL` | Modelo local. Predeterminado `qwen3:4b-instruct`. |
| `OLLAMA_TIMEOUT_SECONDS` | Tiempo máximo de espera de cada solicitud de inferencia. Predeterminado 600 para permitir la carga inicial del modelo en CPU. |
| `STUDYFLOW_API_URL` | URL de FastAPI para Streamlit. Compose usa `http://backend:8000`. |
| `STUDYFLOW_TEST_POSTGRES` | Ejecuta las pruebas en esquemas temporales PostgreSQL cuando vale `1`. |
| `STUDYFLOW_TEST_OLLAMA` | Habilita la prueba de integración real cuando vale `1`. |
| `STUDYFLOW_TEST_CHROMIUM` | Ruta opcional al ejecutable Chromium o Edge para Playwright. |

## Pruebas

Desde la raíz del repositorio, instala las dependencias de desarrollo y ejecuta las pruebas de Streamlit. También puedes ejecutar las pruebas de la API con SQLite en el equipo local.

```powershell
python -m pip install -r backend/requirements-dev.txt -r frontend/requirements.txt -r frontend/requirements-calendar.txt
python -m pytest -q frontend/test_frontend.py
Push-Location backend
python -m pytest -q
Pop-Location
```

Con Compose activo, puedes usar estas variantes de las pruebas del backend.

```powershell
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

## Limitaciones conocidas

- La aplicación está pensada para uso local individual. Los puertos publicados se limitan a loopback y la API carece de autenticación.
- Cada propuesta cubre una actividad. Puede quedar esfuerzo pendiente si la disponibilidad resulta insuficiente.
- El calendario muestra las actividades con plazo, las sesiones de estudio y los compromisos personales. Los calendarios externos se actualizan mediante importación manual de `.ics`.
- El progreso de generación se almacena en memoria y se pierde al reiniciar el backend. Los planes y el seguimiento de sesiones se guardan en la base de datos.
- El modo agente requiere un modelo local descargado y sus estimaciones deben revisarse antes de aprobar el borrador.
