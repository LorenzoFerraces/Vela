# Documentación de entrega — iteración POC (Vela)

**Referencia de release:** [poc](https://github.com/LorenzoFerraces/Vela/releases/tag/poc) (commit `9541571` en el repositorio [LorenzoFerraces/Vela](https://github.com/LorenzoFerraces/Vela)).

## User stories

### 1. Monorepo y fundación del stack (frontend + backend)

**Trello:** [Crear repositorio monorepo](https://trello.com/c/hizd07dW/1-crear-repositorio-monorepo) · [Crear proyecto base de frontend](https://trello.com/c/hx0kCnDC/2-crear-proyecto-base-de-frontend) · [Crear proyecto base de backend](https://trello.com/c/k0WZCVHe/3-crear-proyecto-base-de-backend)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Equipo de desarrollo; usuario final que abre la SPA; clientes HTTP (tests, scripts). |
| **Funcionalidad** | Un repositorio Git con **`backend/`** y **`frontend/`**, README y ejemplos de entorno. **Frontend:** Vite + React + TypeScript, React Router, layout (`Layout`, `Navbar`), estilos base y cliente HTTP en `frontend/src/api/client.ts` (`VITE_API_BASE_URL`). **Backend:** FastAPI con prefijo `/api`, `create_app`, CORS, manejo de errores y routers modulares (contenedores, imágenes, builder, tráfico); arranque con uvicorn/`run.py`; dependencias en `pyproject.toml`. Separación HTTP (`app/api/`) vs dominio (`app/core/`). |
| **Valor** | Clonado único y convenciones compartidas para evolucionar UI y API con builds reproducibles. |
| **Criterios de aceptación** | Clonar y seguir el README permite trabajar en ambas carpetas; `npm ci` + `npm run dev` levantan la SPA; `npm run build` compila; el servidor expone rutas bajo `/api`; tests de integración montan la app con dependencias sustituidas (Docker no obligatorio para la suite base). |

---

### 2. Salud de la API y conectividad desde la pantalla inicial

**Trello:** [Backend: health check para informar que está levantado](https://trello.com/c/Iq72hytX/11-backend-health-check-para-informar-que-est%C3%A1-levantado) · [Pantalla inicial: mostrar un check de conexión contra un backend](https://trello.com/c/sPmKL2rb/10-pantalla-inicial-mostrar-un-check-de-conexi%C3%B3n-contra-un-backend)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Visitante en `/` (home); operadores, CI y E2E que validan que el proceso API responde. |
| **Funcionalidad** | **`GET /api/health`** público, JSON `{"status": "ok"}`, sin auth ni DB en el POC. La home llama `getHealth()` y muestra estado **pendiente** (punto gris), **OK** (verde + texto del estado) o **error** (rojo + mensaje amigable; fallos de red con copy en español cuando aplica). |
| **Valor** | Señal mínima de “¿la API está viva?” y de “¿el frontend la alcanza?” sin herramientas externas. |
| **Criterios de aceptación** | `curl` o navegador a `/api/health` → 200 y cuerpo esperado; con API arriba la home muestra éxito; con API caída o URL incorrecta, error comprensible; `role="status"` / `aria-live` en el indicador; tests de integración y `frontend/e2e/api.spec.ts` validan el contrato. |

---

### 3. Orquestación Docker expuesta por la API

**Trello:** [Backend: implementar lógica de manejo de containers](https://trello.com/c/WHej9Svz/4-backend-implementar-logica-de-manejo-de-containers) · [Backend: ejecutar container desde imagen o URL vía API](https://trello.com/c/Zbo1pxuA/16-backend-ejecutar-container-desde-imagen-o-url-via-api) · [Backend: listar containers y su estado](https://trello.com/c/Y8h6YoF6/17-backend-listar-containers-y-su-estado)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Cliente de la API (SPA, `curl`, scripts); la capa HTTP que delega en el orquestador. |
| **Funcionalidad** | Contrato `ContainerOrchestrator` e implementación **Docker** (`DockerOrchestrator`): deploy con `DeployConfig`, start/stop/remove, health del contenedor, pull de imágenes y errores de dominio mapeados a HTTP; integración con **builder** (imagen vs Git) y con **cableado de rutas** tras deploy cuando hay `route_host`. **`POST /api/containers/run`** acepta imagen Docker o URL Git (`git@`, `http(s)://`, `ssh://`); endpoints auxiliares de disponibilidad de imagen, start/stop/remove. **`GET /api/containers/`** devuelve `ContainerInfo` (id, nombre, imagen, estado, puertos, etiquetas, health) con filtro opcional `status`. En el snapshot **poc**, las rutas de contenedores **no** exigen JWT. |
| **Valor** | Punto único para materializar y consultar workloads sin CLI de Docker; lógica de ciclo de vida fuera de los handlers. |
| **Criterios de aceptación** | Imagen pública válida → contenedor según configuración; Git con Dockerfile → build y run; imagen inexistente o registro → respuestas controladas; listado **200** con array JSON; tests de integración con orquestador mockeado cubren rutas principales (`test_list_containers` y afines); deploy real requiere Docker según README. |

---

### 4. Página Containers: desplegar y operar workloads

**Trello:** [Frontend: Containers page — formulario de creación](https://trello.com/c/ee11pikM/14-frontend-containers-page-formulario-de-creacion) · [Frontend: Containers page — lista running workloads](https://trello.com/c/mIUipMEW/15-frontend-containers-page-lista-running-workloads)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Usuario de **`/containers`** que crea y administra cargas. |
| **Funcionalidad** | **Formulario:** imagen o URL Git, nombre opcional, rama y puerto de app cuando la fuente es Git, puerto en contenedor para imágenes; validación debounced de **disponibilidad de imagen**; envío con `public_route: true` y sin mapeo de puerto en host en el flujo UI del POC; banners de éxito/error. **Tabla Running workloads:** alimentada por `GET /api/containers/` (nombre, imagen, estado, puertos); acciones Start, Stop, Remove; Refresh; estados de carga y vacío. |
| **Valor** | Flujo guiado para desplegar y controlar el ciclo de vida básico sin conocer Docker/Traefik a mano. |
| **Criterios de aceptación** | Campos obligatorios validados; imagen inexistente bloquea envío con mensaje claro; Git muestra rama/puerto según tipo de fuente; tras éxito se refresca la lista; acciones actualizan la tabla; confirmación antes de eliminar; con contenedores Vela en Docker, datos coherentes con el motor. |

---

### 5. Acceso público vía Traefik y URL tras el despliegue

**Trello:** [Backend enrutamiento: integrar Traefik y agregar hostname público](https://trello.com/c/TfKrGqA3/18-backend-enrutamiento-integrar-traefik-y-agregar-hostname-publico) · [Frontend: mostrar URL de acceso público tras correr container](https://trello.com/c/LxhaDWjF/19-frontend-mostrar-url-de-acceso-p%C3%BAblico-tras-correr-container)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Operador que configura Traefik; usuario que despliega con ruta pública y valida el acceso en el navegador. |
| **Funcionalidad** | Capa **`TrafficRouter`**: noop por defecto y **Traefik archivo dinámico JSON** (`traefik_file`). Con `public_route`, asignación de hostname bajo `VELA_PUBLIC_ROUTE_DOMAIN`, registro en Traefik y recarga opcional (`SIGHUP` al contenedor Traefik si está configurado). Si el cableado falla, rollback del contenedor para evitar estado inconsistente. Tras `POST /api/containers/run` exitoso, la UI muestra **`public_url`** como enlace, mensaje de éxito y **Copy URL**. |
| **Valor** | HTTP(S) al servicio sin publicar puertos en el host y feedback inmediato del enlace para probar el deploy. |
| **Criterios de aceptación** | Con `VELA_TRAFFIC_ROUTER=traefik_file`, red y archivo configurados, deploy con ruta pública genera hostname y entrada en Traefik; la UI muestra URL clicable y copia al portapapeles; enlace abre en nueva pestaña; pruebas de integración cubren cableado con router simulado donde aplica. |

---

### 6. CI en GitHub y pruebas E2E (spike → Playwright)

**Trello:** [Setear CI en repositorio](https://trello.com/c/mPqk852m/7-setear-ci-en-repositorio) · [Spike: investigar bibliotecas de testeo e2e](https://trello.com/c/sk93ayqi/12-spike-investigar-bibliotecas-de-testeo-e2e)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Equipo de desarrollo; revisores de PR; pipeline de GitHub Actions. |
| **Funcionalidad** | **Spike** que consolidó **Playwright** (frente a alternativas tipo Cypress) con `playwright.config.ts`, arranque de Vite + uvicorn en modo test y specs en `frontend/e2e/` (humo, contenedores, health contra API real). **CI:** workflows `backend-tests.yml` (pytest en `backend/`) y `e2e.yml` (Node, Chromium, Playwright) con filtros `paths`; artefacto de reporte Playwright con retención limitada. |
| **Valor** | Regresión automática en push/PR sin repetir pasos manuales; harness E2E mantenible alineado con el monorepo. |
| **Criterios de aceptación** | Workflows se disparan según `paths` configurados; en entorno limpio `pytest` y `npm run test:e2e` pasan en el tag **poc**; README documenta ejecución local (incl. variantes headed/UI de Playwright). |

---

## Resumen ejecutivo

### Qué se entregó en esta iteración

- **Monorepo** con SPA Vite/React y API FastAPI, listos para extender con la misma estructura de carpetas y contratos HTTP.
- **Observabilidad mínima:** `GET /api/health` y home con indicador de conectividad.
- **Producto núcleo:** orquestación Docker por API (run desde imagen o Git, listado, start/stop/remove) y página **Containers** que lo expone de punta a punta.
- **Edge routing:** Traefik por archivo dinámico, hostnames públicos y URL mostrada/copiable tras el deploy.
- **Calidad:** pytest en CI, spike E2E resuelto con Playwright y workflow dedicado.

### Decisiones tomadas (prioridades, diseño, riesgos)

- **Traefik vía JSON** y recarga por señal al contenedor, por limitaciones habituales de file watch en Docker Desktop (README).
- **Dos workflows** con `paths` para no ejecutar jobs innecesarios.
- **Dependencias fijadas** (sin rangos `^`/`~` en entradas clave del proyecto).
- En el snapshot **poc**, la API de contenedores es **pública** (sin JWT en esas rutas); iteraciones posteriores al tag añaden autenticación y multitenencia.
- **Playwright** como único harness E2E adoptado tras el spike, integrado en CI y documentado en README.

---
