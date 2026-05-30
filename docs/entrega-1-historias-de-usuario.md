# Documentación de entrega — iteración Entrega-1 (Vela)

**Referencia de release:** [Entrega-1](https://github.com/LorenzoFerraces/Vela/releases/tag/Entrega-1) (commit `c7e006f` en el repositorio [LorenzoFerraces/Vela](https://github.com/LorenzoFerraces/Vela)).

## User stories

### 1. Cuentas, sesión y workloads aislados por usuario

**Trello:** [Modelo de usuario y contenedores en PostgreSQL](https://trello.com/c/iCO5Qpwz/20-modelo-de-usuario-y-contenedores-en-postgresql) · [Backend: API y flujo de registro o login](https://trello.com/c/3sFDjJ0H/21-backend-api-y-flujo-de-registro-o-login) · [Frontend: pantallas de login y sesión](https://trello.com/c/4j13iZ0Z/24-frontend-pantallas-de-login-y-sesi%C3%B3n) · [Proteger rutas de contenedores con autenticación](https://trello.com/c/2VUyyyoh/22-proteger-rutas-de-contenedores-con-autenticaci%C3%B3n) · [Filtrar contenedores por usuario creador](https://trello.com/c/D0V2Qu2Q/23-filtrar-contenedores-por-usuario-creador)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Persona que se registra o inicia sesión; usuario autenticado que opera la plataforma; cliente anónimo (recibe 401). |
| **Funcionalidad** | **Persistencia:** PostgreSQL con tabla `users` (email único, hash de contraseña), `user_oauth_identities` y modelos de dominio asociados (`images`, `dockerfiles`); migraciones Alembic. Los contenedores en ejecución siguen en Docker; el vínculo usuario↔workload es la etiqueta `vela.owner_id`, no una fila “container” en SQL. **Auth API:** `POST /api/auth/register`, `POST /api/auth/login` y `GET /api/auth/me` con JWT Bearer. **SPA:** rutas `/login` y `/register`, `AuthProvider` con token en `localStorage` (`vela.access_token`), cliente HTTP con encabezado Bearer y `RequireAuth` en dashboard, containers, builder y settings. **Multitenencia:** rutas bajo `/api/containers/` exigen usuario autenticado; en deploy se aplica `vela.owner_id`; `GET /api/containers/` lista solo workloads del dueño; operaciones sobre un id concreto pasan por `_require_owned` (404 si la etiqueta no coincide). |
| **Valor** | Cada cuenta tiene identidad persistente, sesión en el navegador y un inventario de cargas que no se mezcla con el de otros usuarios ni se manipula sin credenciales. |
| **Criterios de aceptación** | `alembic upgrade head` aplica el esquema; register/login/me cubiertos por tests de integración; sin token → **401** en rutas protegidas; con token de otro usuario → **404** en recurso ajeno; tras desplegar con usuarios A y B, cada listado devuelve solo sus filas; registro o login exitoso lleva al área autenticada y la recarga conserva sesión mientras el JWT sea válido; rutas protegidas sin token redirigen a `/login?next=…`; E2E en `frontend/e2e/auth.spec.ts` ejercitan flujos de auth. |

---

### 2. Integración GitHub: conectar cuenta y desplegar repos privados

**Trello:** [OAuth GitHub: callback y almacenamiento de tokens](https://trello.com/c/d39gvNme/26-oauth-github-callback-y-almacenamiento-de-tokens) · [Frontend: conectar y mostrar estado de cuenta GitHub](https://trello.com/c/Lnwy7kfO/27-frontend-conectar-y-mostrar-estado-de-cuenta-github) · [Build y clone con repos privados usando token del usuario](https://trello.com/c/YSvNDKIj/28-build-y-clone-con-repos-privados-usando-token-del-usuario)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Usuario autenticado que enlaza GitHub en Settings y despliega desde URLs `https://github.com/…`. |
| **Funcionalidad** | **OAuth:** `GET /api/auth/github/start` devuelve la URL de autorización; `GET /api/auth/github/callback` intercambia el código, obtiene perfil, cifra el access token (Fernet, `VELA_TOKEN_ENCRYPTION_KEY`) y hace upsert en `user_oauth_identities`; redirección al frontend (`/settings?github=connected` o `?github=error&reason=…`) sin exponer el token en JSON; `GET /api/auth/github/status` y `DELETE /api/auth/github` para consulta y desconexión. **UI Settings:** estado conectado/desconectado, login y avatar, flujo guiado de conexión y banners tras el callback. **Deploy privado:** en `POST /api/containers/run` (y análisis de fuente git en builder cuando aplica), el backend resuelve el token del usuario y configura clone vía `git -c http.extraheader=Authorization: Basic …` sin pegar PAT en el formulario ni filtrar el secreto en URLs o logs. |
| **Valor** | Repos privados desplegables con OAuth estándar; el usuario ve en todo momento si GitHub está vinculado y puede revocar la integración sin editar variables locales con tokens en claro. |
| **Criterios de aceptación** | Callback persiste identidad cifrada y redirige a Settings (tests en `test_github_oauth.py`); `/github/status` nunca devuelve el token; tras OAuth exitoso la UI muestra “conectado” y tras disconnect, desconectado; despliegue de repo privado sin GitHub conectado falla con mensaje que orienta a Settings; con identidad almacenada el clone/build puede completarse; README documenta `VELA_GITHUB_*`, `VELA_FRONTEND_BASE_URL` y `VELA_TOKEN_ENCRYPTION_KEY`. |

---

### 3. Inventario y monitoreo de workloads en ejecución

**Trello:** [Lista running workloads: copiar URL de acceso al contenedor](https://trello.com/c/PZaFCaHI/37-lista-running-workloads-copiar-url-de-acceso-al-contenedor) · [Lista running workloads: vista opcional o expandible de logs por contenedor](https://trello.com/c/lCkjLb0X/49-lista-running-workloads-vista-opcional-o-expandible-de-logs-por-contenedor) · [Dashboard de monitoreo: panel de logs del contenedor con errores de arranque y ejecución](https://trello.com/c/fPo2TqYE/48-dashboard-de-monitoreo-panel-de-logs-del-contenedor-con-errores-de-arranque-y-ejecuci%C3%B3n)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Usuario autenticado en **Containers** o **Dashboard** que opera y diagnostica cargas ya desplegadas. |
| **Funcionalidad** | Tabla compartida `WorkloadsTable` en ambas páginas: columna **Access URL** con botón **Copy** (`access_url` al portapapeles, feedback Copied/Copy failed, **—** si no hay ruta pública Traefik); columna **Logs** con **Show/Hide** que despliega panel bajo la fila — snapshot vía `GET …/logs` si no está running, **WebSocket** `…/logs/stream` en vivo si está running (token en query `access_token`), opción **Highlight error lines** y **Refresh snapshot**. En **Dashboard**, `prioritizeProblemWorkloads` ordena primero contenedores detenidos, en reinicio o con health no saludable. Rutas y WS validan Bearer y propiedad antes de streamear. |
| **Valor** | Una sola superficie para ver qué está fallando, abrir o copiar la URL pública y leer trazas de arranque o runtime sin salir de la app ni usar `docker logs` a mano. |
| **Criterios de aceptación** | Con `access_url` informada, copiar deja la URL exacta en el portapapeles; expandir logs muestra trazas y estados Connecting/Live/Ended/Error; colapsar cierra el socket; en Dashboard el orden prioriza cargas problemáticas; `/dashboard` y `/containers` exigen `RequireAuth`; backend rechaza acceso a logs de contenedor ajeno; verificación manual o E2E en `dashboard.spec.ts` / `containers.spec.ts` donde existan. |

---

### 4. Autocompletado de imágenes al desplegar un contenedor

**Trello:** [Backend y UI: autocompletado de imágenes según las más pulleadas del registry](https://trello.com/c/ztqfVIcc/42-backend-y-ui-autocompletado-de-im%C3%A1genes-seg%C3%BAn-las-m%C3%A1s-pulleadas-del-registry)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Usuario autenticado que completa el campo de imagen en el formulario de run en **Containers**. |
| **Funcionalidad** | `GET /api/containers/image/suggestions` (autenticado) fusiona imágenes locales del motor Docker con sugerencias de **Docker Hub** (`merge_image_suggestions`, metadatos de pull); la UI consume el endpoint con búsqueda debounced en el flujo del formulario. |
| **Valor** | Menos errores de tipeo y descubrimiento de imágenes populares sin consultar el hub manualmente. |
| **Criterios de aceptación** | Sin autenticación → 401; query vacío devuelve refs locales sin invocar Hub donde el código lo define; con `q=` la respuesta incluye `ref`, `pull_count` y `source`; tests `test_image_suggestions_*` en integración pasan. |

---

### 5. Regresión end-to-end con Playwright en CI

**Trello:** [Agregar testeo con Cypress / Playwright](https://trello.com/c/AGS7zQqy/6-agregar-testeo-con-cypress-playwright)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Equipo de desarrollo y revisores de PR; pipeline de GitHub Actions. |
| **Funcionalidad** | Suite **Playwright** en `frontend/e2e/` (auth, settings, dashboard, containers, builder, smoke, API health) contra frontend y API reales vía `playwright.config.ts` (Vite + uvicorn en modo test). Workflow `.github/workflows/e2e.yml` con Chromium y artefacto de reporte (retención acotada). **Cypress** no está integrado: la entrega consolidó un solo harness E2E. |
| **Valor** | Regresión automática de flujos críticos en navegador real, alineada con la política del repo de no stubear `/api/**` en specs de producto. |
| **Criterios de aceptación** | `npm run test:e2e` pasa en entorno limpio según README; el workflow se dispara con los `paths` configurados y adjunta el reporte Playwright; en la rama/tag **Entrega-1** la suite refleja el alcance descrito arriba. |

---

## Resumen ejecutivo

### Qué se entregó en esta iteración

- **Plataforma multiusuario:** identidad en PostgreSQL, JWT, login/registro en la SPA y API de contenedores acotada por dueño (`vela.owner_id` + comprobación de propiedad).
- **GitHub como proveedor de identidad y clone:** OAuth con token cifrado, Settings con estado visible y despliegue de repos privados sin PAT en el formulario.
- **Operación de workloads:** tabla unificada en Containers y Dashboard con copia de URL pública, logs por HTTP/WebSocket y vista de monitoreo que prioriza cargas problemáticas.
- **UX de despliegue:** sugerencias de imagen locales + Docker Hub en el formulario de run.
- **Calidad:** E2E con Playwright en local y CI (sin Cypress).

### Decisiones tomadas (prioridades, diseño, riesgos)

- **Playwright** como única herramienta E2E del monorepo para reducir mantenimiento frente a Cypress.
- **Propiedad de contenedores** vía etiquetas Docker en lugar de tabla SQL de inventario: simplicidad operativa; el listado depende del estado del motor además del dueño.
- **WebSocket de logs** con `access_token` en query y validación de usuario en el handler, coherente con limitaciones del API de WebSocket en navegador.
- **Sugerencias de imágenes:** mezcla motor local + metadatos públicos de Docker Hub; consultas vacías acotadas para no golpear el hub innecesariamente.
- **Callback OAuth** siempre redirige a la SPA (nunca JSON de error en bruto) para no dejar al usuario fuera de la interfaz.

---
