# Documentación de entrega — iteración Entrega-1 (Vela)

**Referencia de release:** [Entrega-1](https://github.com/LorenzoFerraces/Vela/releases/tag/Entrega-1) (commit `c7e006f` en el repositorio [LorenzoFerraces/Vela](https://github.com/LorenzoFerraces/Vela)).

## User stories

### 1. Proteger rutas de contenedores con autenticación

**Trello:** [Proteger rutas de contenedores con autenticación](https://trello.com/c/2VUyyyoh/22-proteger-rutas-de-contenedores-con-autenticaci%C3%B3n)


| Campo                       | Descripción                                                                                                                                                                                                                                                                                                                                         |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Usuario autenticado que usa la API o la SPA; cliente anónimo (recibe 401).                                                                                                                                                                                                                                                                          |
| **Funcionalidad**           | Las rutas bajo el prefijo `**/api/containers/`** (listado, run, start/stop/remove, logs, WebSocket de logs, sugerencias de imagen, etc.) exigen `**Authorization: Bearer`** válido vía `get_current_user`. Las operaciones sobre un contenedor concreto pasan por `_require_owned` (404 si la etiqueta `vela.owner_id` no coincide con el usuario). |
| **Valor**                   | Ningún cliente puede orquestar ni inspeccionar cargas ajenas por la API.                                                                                                                                                                                                                                                                            |
| **Criterios de aceptación** | Sin token: respuestas **401** en rutas protegidas; con token de otro usuario: **404** en recurso no propio; tests de integración cubren anonimato vs autenticado.                                                                                                                                                                                   |


---

### 2. Filtrar contenedores por usuario creador

**Trello:** [Filtrar contenedores por usuario creador](https://trello.com/c/D0V2Qu2Q/23-filtrar-contenedores-por-usuario-creador)


| Campo                       | Descripción                                                                                                                                                                                                                                                          |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Usuario autenticado que consulta su inventario.                                                                                                                                                                                                                      |
| **Funcionalidad**           | En el **deploy**, la configuración lleva la etiqueta `**vela.owner_id`** con el UUID del usuario. `**GET /api/containers/`** invoca `orchestrator.list(..., owner_id=str(current_user.id))`, de modo que Docker filtra por etiqueta además del flag de gestión Vela. |
| **Valor**                   | Cada cuenta ve solo sus propios workloads aunque compartan motor Docker.                                                                                                                                                                                             |
| **Criterios de aceptación** | Tras desplegar con usuario A y B, cada `GET /api/containers/` devuelve solo filas del dueño; pruebas de integración validan el filtrado con etiquetas esperadas.                                                                                                     |


---

### 3. Frontend: pantallas de login y sesión

**Trello:** [Frontend: pantallas de login y sesión](https://trello.com/c/4j13iZ0Z/24-frontend-pantallas-de-login-y-sesi%C3%B3n)


| Campo                       | Descripción                                                                                                                                                                                                                         |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Persona que se registra o inicia sesión; visitante redirigido a login si intenta rutas protegidas.                                                                                                                                  |
| **Funcionalidad**           | Rutas `**/login`** y `**/register`**; `AuthProvider` guarda el **access token** en `localStorage` (`vela.access_token`); el cliente HTTP adjunta el encabezado Bearer; `RequireAuth` envuelve dashboard, containers, settings, etc. |
| **Valor**                   | Sesión persistente en el navegador y gating de la SPA coherente con la API.                                                                                                                                                         |
| **Criterios de aceptación** | Registro o login exitoso lleva al área autenticada; recarga conserva sesión mientras el token siga siendo válido; rutas protegidas sin token redirigen a `/login`. E2E cubren flujos de auth.                                       |


---

### 4. Backend: API y flujo de registro o login

**Trello:** [Backend: API y flujo de registro o login](https://trello.com/c/3sFDjJ0H/21-backend-api-y-flujo-de-registro-o-login)


| Campo                       | Descripción                                                                                                                                                                                                    |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Cliente SPA o consumidor de la API.                                                                                                                                                                            |
| **Funcionalidad**           | `POST /api/auth/register` crea usuario y devuelve `access_token` + `user`; `POST /api/auth/login` valida email/contraseña y devuelve el mismo shape; `GET /api/auth/me` devuelve el usuario actual con Bearer. |
| **Valor**                   | Autenticación stateless basada en JWT alineada con el resto de rutas protegidas.                                                                                                                               |
| **Criterios de aceptación** | Credenciales inválidas → 401 u error de dominio mapeado; registro duplicado manejado; tests de integración ejercitan register/login/me.                                                                        |


---

### 5. Modelo de usuario y contenedores en PostgreSQL

**Trello:** [Modelo de usuario y contenedores en PostgreSQL](https://trello.com/c/iCO5Qpwz/20-modelo-de-usuario-y-contenedores-en-postgresql)


| Campo                       | Descripción                                                                                                                                                                                                                                                                                                                                                                           |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | La aplicación API; operador de base de datos.                                                                                                                                                                                                                                                                                                                                         |
| **Funcionalidad**           | Tabla `**users`** (email único, hash de contraseña, timestamps); `**user_oauth_identities`** para GitHub; modelos adicionales de dominio (`images`, `dockerfiles`) con FK al usuario. Los **contenedores en ejecución** siguen en Docker; el **vínculo usuario↔contenedor** es la etiqueta `vela.owner_id` en el contenedor, no una fila “container” en SQL. Migraciones **Alembic**. |
| **Valor**                   | Persistencia transaccional para identidad y tokens; la orquestación sigue siendo responsabilidad del motor de contenedores.                                                                                                                                                                                                                                                           |
| **Criterios de aceptación** | `alembic upgrade head` aplica el esquema; las rutas de auth leen/escriben en Postgres vía sesión async; README documenta `VELA_DATABASE_URL` y uso de Postgres en desarrollo.                                                                                                                                                                                                         |


---

### 6. Agregar testeo con Cypress / Playwright

**Trello:** [Agregar testeo con Cypress / Playwright](https://trello.com/c/AGS7zQqy/6-agregar-testeo-con-cypress-playwright)


| Campo                       | Descripción                                                                                                                                                                                                                                                                                          |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | CI y desarrolladores que ejecutan E2E localmente.                                                                                                                                                                                                                                                    |
| **Funcionalidad**           | Suite **Playwright** en `frontend/e2e/` (auth, settings, dashboard, containers, health API); `playwright.config.ts` levanta Vite + uvicorn en modo test; workflow `**.github/workflows/e2e.yml`** con Chromium. **Cypress** no está integrado en el monorepo: la entrega se consolidó en Playwright. |
| **Valor**                   | Regresión automática de flujos críticos en navegador real sin servicios externos en la mayoría de specs (mocks HTTP donde aplica).                                                                                                                                                                   |
| **Criterios de aceptación** | `npm run test:e2e` pasa en limpio con dependencias del README; el workflow de GitHub Actions adjunta el reporte Playwright como artefacto (retención acotada).                                                                                                                                       |


---

### 7. Build y clone con repos privados usando token del usuario

**Trello:** [Build y clone con repos privados usando token del usuario](https://trello.com/c/YSvNDKIj/28-build-y-clone-con-repos-privados-usando-token-del-usuario)


| Campo                       | Descripción                                                                                                                                                                                                                                                                    |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Actor(es)**               | Usuario con cuenta GitHub conectada que despliega desde URL `https://github.com/...`.                                                                                                                                                                                          |
| **Funcionalidad**           | Tras OAuth, el token de GitHub se guarda cifrado (Fernet) y, en `POST /api/containers/run` con fuente privada en GitHub, el backend obtiene el token del usuario y configura **clone** vía cabecera extra (`git -c http.extraheader=...`) sin exponer el token en logs ni URL. |
| **Valor**                   | Repos privados desplegables sin pegar PAT en el formulario.                                                                                                                                                                                                                    |
| **Criterios de aceptación** | Sin GitHub conectado, despliegue de repo privado falla con mensaje claro; con identidad almacenada, el flujo de build puede clonar; README documenta variables OAuth y `VELA_TOKEN_ENCRYPTION_KEY`.                                                                            |


---

### 8. Lista running workloads: vista opcional o expandible de logs por contenedor

**Trello:** [Lista running workloads: vista opcional o expandible de logs por contenedor](https://trello.com/c/lCkjLb0X/49-lista-running-workloads-vista-opcional-o-expandible-de-logs-por-contenedor)


| Campo                       | Descripción                                                                                                                                                                                                                                                                                                                                                                |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Usuario en **Containers** o **Dashboard** que inspecciona una fila concreta.                                                                                                                                                                                                                                                                                               |
| **Funcionalidad**           | En `WorkloadsTable`, columna **Logs** con **Show / Hide** que despliega un panel bajo la fila: si el contenedor **no está running**, snapshot vía `GET .../logs`; si **está running**, **WebSocket** `.../logs/stream` con chunks binarios; opción **Highlight error lines** y **Refresh snapshot**. Autenticación del WS con query `access_token` (patrón del navegador). |
| **Valor**                   | Diagnóstico rápido sin salir de la tabla ni usar `docker logs` manualmente.                                                                                                                                                                                                                                                                                                |
| **Criterios de aceptación** | Expandir muestra trazas; colapsar cierra el socket; estados Connecting / Live / Ended / Error visibles; backend valida token y propiedad antes de streamear.                                                                                                                                                                                                               |


---

### 9. Backend y UI: autocompletado de imágenes según las más pulleadas del registry

**Trello:** [Backend y UI: autocompletado de imágenes según las más pulleadas del registry](https://trello.com/c/ztqfVIcc/42-backend-y-ui-autocompletado-de-im%C3%A1genes-seg%C3%BAn-las-m%C3%A1s-pulleadas-del-registry)


| Campo                       | Descripción                                                                                                                                                                                                                                |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Actor(es)**               | Usuario que completa el campo de imagen en el formulario de run.                                                                                                                                                                           |
| **Funcionalidad**           | `GET /api/containers/image/suggestions` (autenticado) fusiona imágenes locales del motor con sugerencias de **Docker Hub** (`merge_image_suggestions`, conteos de pull); la UI consume el endpoint en el flujo del formulario (debounced). |
| **Valor**                   | Menos errores de tipeo y descubrimiento de imágenes populares sin consultar el hub a mano.                                                                                                                                                 |
| **Criterios de aceptación** | Query vacío omite llamada al hub donde el código lo define; respuesta incluye `ref`, `pull_count`, `source`; tests `test_image_suggestions_`* pasan.                                                                                       |


---

### 10. Lista running workloads: copiar URL de acceso al contenedor

**Trello:** [Lista running workloads: copiar URL de acceso al contenedor](https://trello.com/c/PZaFCaHI/37-lista-running-workloads-copiar-url-de-acceso-al-contenedor)


| Campo                       | Descripción                                                                                                                                                                                                     |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Usuario que necesita compartir o abrir la URL pública del workload.                                                                                                                                             |
| **Funcionalidad**           | Columna **Access URL** en `WorkloadsTable`: botón **Copy** que escribe `access_url` en el portapapeles; feedback **Copied** / **Copy failed**; si no hay ruta Traefik, se muestra **—** con título explicativo. |
| **Valor**                   | Misma conveniencia que el banner post-run, pero desde el inventario en curso.                                                                                                                                   |
| **Criterios de aceptación** | Con `access_url` informada por la API, el portapapeles contiene la URL exacta; sin URL, no hay botón de copia; verificación manual o cobertura E2E si existe.                                                   |


---

### 11. Dashboard de monitoreo: panel de logs del contenedor con errores de arranque y ejecución

**Trello:** [Dashboard de monitoreo: panel de logs del contenedor con errores de arranque y ejecución](https://trello.com/c/fPo2TqYE/48-dashboard-de-monitoreo-panel-de-logs-del-contenedor-con-errores-de-arranque-y-ejecuci%C3%B3n)


| Campo                       | Descripción                                                                                                                                                                                                                                                                               |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Usuario autenticado en `**/dashboard`**.                                                                                                                                                                                                                                                  |
| **Funcionalidad**           | Página **Dashboard** con `WorkloadsTable` en modo `**prioritizeProblemWorkloads`**: contenedores detenidos, en reinicio o con health no saludable aparecen primero. Los logs expandibles y el resaltado de líneas de error cubren arranque y runtime en el mismo panel que en Containers. |
| **Valor**                   | Vista operativa centrada en “qué está roto o inestable” y por qué (logs), separada del flujo de creación.                                                                                                                                                                                 |
| **Criterios de aceptación** | Orden de filas coherente con la política de prioridad; logs accesibles como en la lista de Containers; ruta protegida por `RequireAuth`.                                                                                                                                                  |


---

### 12. OAuth GitHub: callback y almacenamiento de tokens

**Trello:** [OAuth GitHub: callback y almacenamiento de tokens](https://trello.com/c/d39gvNme/26-oauth-github-callback-y-almacenamiento-de-tokens)


| Campo                       | Descripción                                                                                                                                                                                                                                                                                                                                                            |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Usuario que conecta GitHub; el servidor que intercambia `code` por token.                                                                                                                                                                                                                                                                                              |
| **Funcionalidad**           | `GET /api/auth/github/start` devuelve URL de autorización; `GET /api/auth/github/callback` intercambia el código, obtiene perfil, **cifra** el access token y hace upsert en `user_oauth_identities`; redirección al frontend con `?github=connected` o error; `DELETE /api/auth/github` revoca fila y token. Variables `VELA_GITHUB_`* y `VELA_TOKEN_ENCRYPTION_KEY`. |
| **Valor**                   | Integración OAuth estándar sin almacenar secretos en claro en base de datos.                                                                                                                                                                                                                                                                                           |
| **Criterios de aceptación** | El callback no expone el token al navegador en JSON; estado y desconexión por rutas documentadas en README; pruebas cubren ramas relevantes donde existan.                                                                                                                                                                                                             |


---

### 13. Frontend: conectar y mostrar estado de cuenta GitHub

**Trello:** [Frontend: conectar y mostrar estado de cuenta GitHub](https://trello.com/c/Lnwy7kfO/27-frontend-conectar-y-mostrar-estado-de-cuenta-github)


| Campo                       | Descripción                                                                                                                                                                                                              |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Actor(es)**               | Usuario en **Settings** que enlaza o desvincula GitHub.                                                                                                                                                                  |
| **Funcionalidad**           | UI que llama a `GET /api/auth/github/status` y muestra conexión, login y avatar si aplica; acción para abrir **start** OAuth; manejo de query `github=connected` / error al volver del callback; desconexión vía DELETE. |
| **Valor**                   | Transparencia del estado de integración y flujo guiado sin editar `.env` con tokens manuales.                                                                                                                            |
| **Criterios de aceptación** | Tras OAuth exitoso, la pantalla refleja “conectado”; tras disconnect, estado desconectado; mensajes de error legibles según `detail` de la API.                                                                          |


---

## Resumen ejecutivo

### Qué se agregó o modificó en esta iteración

- **Autenticación** JWT (registro, login, `/me`) y **protección** de la API de contenedores y rutas relacionadas.
- **PostgreSQL** para usuarios, identidades OAuth y modelos asociados; **multitenencia** en Docker vía etiqueta `**vela.owner_id`**.
- **GitHub OAuth** (callback, cifrado en reposo, estado y desconexión) y **clone/build de repos privados** con el token del usuario.
- **UX de workloads**: **URL de acceso** con copia, **sugerencias de imágenes**, tabla compartida en **Containers** y **Dashboard**.
- **Observabilidad**: logs por HTTP y **WebSocket**; fila expandible con resaltado de errores; en Dashboard, **priorización** de cargas problemáticas.
- **CI E2E** con Playwright y documentación de ejecución en README (alineado con las notas del release).

### Decisiones tomadas (prioridades, diseño, riesgos)

- **Playwright** como herramienta E2E en el repo (sin Cypress) para un solo harness y menos mantenimiento.
- **Propiedad de contenedores** con etiquetas Docker en lugar de tabla SQL de contenedores: simplicidad operativa; inventario depende también del estado del motor.
- **WebSocket de logs** con `access_token` en query y validación de usuario en handler; sesión DB inyectada donde aplica para coherencia con el resto de la API.
- **Endpoints WebSocket** para acceso a logs, facilitando el acceso a una consola en un futuro
- **Sugerencias de imágenes**: mezcla motor local + metadatos públicos Docker Hub; comportamiento sin query acotado en código.

---

