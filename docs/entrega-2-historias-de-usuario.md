# Documentación de entrega — iteración 2: Deploy, Builder e historial (Vela)

**Ámbito de código:** commit `1c555cc` en el repositorio [LorenzoFerraces/Vela](https://github.com/LorenzoFerraces/Vela) (HEAD al redactar; sin tag de release publicado aún).

## User stories

### 1. Biblioteca personal de Dockerfiles (Builder)

**Trello:** [PostgreSQL: tablas para dockerfiles por usuario](https://trello.com/c/0H9szlq8/29-postgresql-tablas-para-dockerfiles-por-usuario) · [API CRUD de dockerfiles](https://trello.com/c/i3SUgCt5/30-api-crud-de-dockerfiles) · [Frontend: pestaña Builder — listar, editar y guardar dockerfile](https://trello.com/c/W5O8x6ph/31-frontend-pesta%C3%B1a-builder-listar-editar-y-guardar-dockerfile)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Usuario autenticado que reutiliza plantillas de build en varios despliegues. |
| **Funcionalidad** | Tabla **`dockerfiles`** en PostgreSQL (`owner_id`, `name` único por usuario, `contents`, timestamps) con migración Alembic. API autenticada **`GET/POST /api/dockerfiles/`**, **`GET/PATCH/DELETE /api/dockerfiles/{id}`** vía `user_library`. Página **`/builder`**: listar plantillas, crear, seleccionar, editar nombre/contenido, guardar y eliminar; banners de éxito/error. Las plantillas se ofrecen luego como fuente de deploy (historia 2). |
| **Valor** | Dockerfile reutilizable y versionado en cuenta, sin depender solo del motor Docker ni de pegar el mismo archivo en cada run. |
| **Criterios de aceptación** | `alembic upgrade head` crea `dockerfiles`; CRUD solo devuelve/modifica filas del usuario actual; nombre duplicado → 400; tests en `test_user_library_api.py`; E2E `frontend/e2e/builder.spec.ts` cubre listado y edición; README documenta la sección “User library”. |

---

### 2. Desplegar desde una fuente unificada (formulario simplificado en Containers)

**Trello:** [Frontend: simplificación del formulario de run en Containers](https://trello.com/c/xDNkyBvC/50-frontend-simplificaci%C3%B3n-del-formulario-de-run-en-containers) · [Backend y UI: búsqueda unificada de fuente de deploy](https://trello.com/c/HpSE5kcL/51-backend-y-ui-b%C3%BAsqueda-unificada-de-fuente-de-deploy)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Usuario autenticado en **`/containers`** que elige qué desplegar. |
| **Funcionalidad** | Un único campo **Deploy source** (`DeploySourceCombobox`) sustituye flujos separados de imagen/Git/plantilla: búsqueda debounced contra **`GET /api/containers/deploy-sources?q=&limit=`**, que agrega sugerencias de **imagen** (local + registry), **repos GitHub** (con token del usuario si está conectado) y **plantillas Dockerfile** del usuario. Al elegir una sugerencia, el formulario adapta campos (p. ej. rama Git solo para fuente git); validación de disponibilidad de imagen cuando aplica; `POST /api/containers/run` con `source_kind` `image` \| `git` \| `dockerfile_template`. El flujo UI mantiene `public_route: true` y puerto de contenedor por defecto acorde a AGENTS.md. |
| **Valor** | Menos fricción al desplegar: una búsqueda, un botón **Build**, sin alternar modos de fuente a mano. |
| **Criterios de aceptación** | Combobox visible con etiqueta “Deploy source”; sugerencias agrupadas por tipo; sin selección → mensaje al enviar; E2E `containers.spec.ts` elige `nginx:alpine` vía opción y completa build con URL pública; test `test_deploy_sources_includes_dockerfile_template` valida que las plantillas del usuario aparecen en sugerencias. |

---

### 3. Variables de entorno y comando de arranque al crear un contenedor

**Trello:** [Backend: variables de entorno y comando de inicio en creación desde fuente](https://trello.com/c/DftAdsVB/35-backend-variables-de-entorno-y-comando-de-inicio-en-creaci%C3%B3n-desde-fuente) · [Frontend: variables de entorno y comando de inicio en formulario de creación de contenedor](https://trello.com/c/apfrxLvu/36-frontend-variables-de-entorno-y-comando-de-inicio-en-formulario-de-creaci%C3%B3n-de-contenedor)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Usuario que ajusta el runtime del workload antes del deploy. |
| **Funcionalidad** | **`RunFromSourceRequest`** acepta `env_vars` (mapa validado) y `command` (lista opcional de tokens para sobrescribir CMD). La UI expone bloque colapsable **Advanced options**: filas clave/valor editables y campo de comando con parseo tipo shell (`parseStartCommand` / `recordFromEnvRows`); los valores se envían en cada `run` para imagen, Git o plantilla. El orquestador aplica env y command en `DeployConfig`. |
| **Valor** | Configuración de runtime explícita sin editar la imagen ni usar solo variables del host. |
| **Criterios de aceptación** | Deploy con `env_vars` y `command` llega al motor con esos valores; `test_run_creates_deployment_record` verifica persistencia en historial (env sensibles redactados en listado); formulario muestra Advanced options expandible; comando vacío → `null` en API. |

---

### 4. Análisis de repositorio Git y pre-relleno del formulario de deploy

**Trello:** [Frontend: build con URL GitHub — disparar análisis y rellenar formulario](https://trello.com/c/jglHveL7/41-frontend-build-con-url-github-disparar-an%C3%A1lisis-y-rellenar-formulario)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Usuario con fuente **git** en el combobox que quiere inferir puerto, nombre, env y comando. |
| **Funcionalidad** | Botón **Analyze** (icono spark) junto al nombre cuando la fuente es Git; llama **`POST /api/builder/analyze-source`** con `git_url` y `git_branch` (clone con token OAuth si el repo es privado). Backend: clone temporal, lectura de archivos de contexto y sugerencia vía **Gemini** (`VELA_GEMINI_API_KEY`) o fixture E2E; respuesta `GitSourceAnalysis`. Frontend aplica campos según preferencias **`GET/PATCH /api/settings/ai-prefill`** (rama, puerto, nombre, env, start_command). |
| **Valor** | Menos adivinanza al desplegar repos desconocidos; un clic propone valores coherentes con el stack detectado. |
| **Criterios de aceptación** | Con fuente git, el botón Analyze es visible; éxito actualiza puerto/nombre/rama/env/comando según prefs; error muestra mensaje API amigable; `test_analyze_git_source_e2e_fixture` y tests de prefill en `test_deploy_epic.py`; sin API key de Gemini, comportamiento documentado en README (fallo controlado o E2E). |

---

### 5. Historial de despliegues con autor y diff entre versiones

**Trello:** [Historial de despliegues con autor y diff de env y dockerfile entre versiones](https://trello.com/c/5zumSTi3/46-historial-de-despliegues-con-autor-y-diff-de-env-y-dockerfile-entre-versiones)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Usuario autenticado en **Dashboard** que audita qué se desplegó y qué cambió entre runs. |
| **Funcionalidad** | Tabla **`deployment_records`** (snapshot por `POST /api/containers/run` exitoso: fuente, imagen, puerto, env, command, snapshot de Dockerfile, URL pública, contenedor). API **`GET /api/deployments/`**, **`GET /api/deployments/{id}`**, **`GET /api/deployments/diff?left=&right=`** con diff de env (added/removed/changed) y diff unificado de Dockerfile (`difflib`). Listados incluyen **`author_email`** del usuario. UI **`DeploymentHistorySection`** en Dashboard: tabla de despliegues, selección de dos filas y panel de diff; refresco tras nuevo deploy. Valores sensibles de env en listado aparecen como `<REDACTED>`. |
| **Valor** | Trazabilidad por cuenta: quién desplegó qué, y comparación rápida de configuración entre dos versiones. |
| **Criterios de aceptación** | Cada run exitoso genera al menos un registro; diff entre dos ids del mismo usuario devuelve cambios de env y líneas de Dockerfile; `test_deployment_diff` pasa; E2E `dashboard.spec.ts` — “deploy history lists recent deployments”; diff vacío muestra copy “No env changes” / “No Dockerfile diff” cuando aplica. |

---

## Resumen ejecutivo

### Qué se entregó en esta iteración

- **Builder:** plantillas Dockerfile por usuario en Postgres con CRUD API y UI dedicada.
- **Deploy en Containers:** combobox unificado de fuentes (imagen, GitHub, plantilla) y formulario acotado al flujo “buscar → configurar → Build”.
- **Runtime configurable:** variables de entorno y comando de arranque en API y sección avanzada del formulario.
- **Asistencia Git:** análisis de repo con pre-relleno guiado por preferencias de IA (Gemini + OAuth para privados).
- **Historial:** registro de cada deploy con autor, consulta y diff env/Dockerfile en Dashboard.

### Decisiones tomadas (prioridades, diseño, riesgos)

- **Plantillas en SQL**, no en el motor Docker: inventario de imágenes (`/api/images`) sigue separado del catálogo de Dockerfiles reutilizables.
- **Un solo endpoint de sugerencias** (`deploy-sources`) frente a tres entradas de formulario, con orden imagen → plantilla → Git en la respuesta.
- **Opciones avanzadas colapsadas** para no abrumar el run habitual; puerto/contenedor público fijos según convención del producto.
- **Análisis Git opcional** y dependiente de `VELA_GEMINI_API_KEY`; E2E usa fixture para no llamar a modelos externos en CI.
- **Historial:** env vars redactados en listado; diff solo entre registros del mismo usuario; fallo al persistir historial no revierte el deploy (se registra en logs).

---
