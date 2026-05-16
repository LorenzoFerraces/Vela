# Documentación de entrega — iteración POC (Vela)

**Referencia de release:** [poc](https://github.com/LorenzoFerraces/Vela/releases/tag/poc) (commit `9541571` en el repositorio [LorenzoFerraces/Vela](https://github.com/LorenzoFerraces/Vela)).

## User stories

### 1. Crear proyecto base de frontend

**Trello:** [Crear proyecto base de frontend](https://trello.com/c/hx0kCnDC/2-crear-proyecto-base-de-frontend)


| Campo                       | Descripción                                                                                                                                                                                                                                                                                      |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Actor(es)**               | Equipo de desarrollo; usuario final que accede a la SPA en el navegador.                                                                                                                                                                                                                         |
| **Funcionalidad**           | Monorepo con aplicación **Vite + React + TypeScript**, enrutamiento con **React Router**, estilos base (`index.css`), componentes de layout (`Layout`, `Navbar`) y páginas iniciales. Cliente HTTP centralizado en `frontend/src/api/client.ts` con URL base configurable (`VITE_API_BASE_URL`). |
| **Valor**                   | Base técnica homogénea para evolucionar la UI, compilar y desplegar el frontend de forma predecible.                                                                                                                                                                                             |
| **Criterios de aceptación** | `npm ci` y `npm run dev` levantan la app (p. ej. en `http://127.0.0.1:5173`); existe estructura de `src/` con páginas y componentes; el proyecto compila con `npm run build`.                                                                                                                    |


---

### 2. Crear proyecto base de backend

**Trello:** [Crear proyecto base de backend](https://trello.com/c/k0WZCVHe/3-crear-proyecto-base-de-backend)


| Campo                       | Descripción                                                                                                                                                                                                                                                           |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Equipo de desarrollo; clientes HTTP (SPA, scripts, tests).                                                                                                                                                                                                            |
| **Funcionalidad**           | API **FastAPI** con prefijo `/api`, fábrica de aplicación (`create_app`), middleware **CORS**, manejadores de errores y routers modulares (contenedores, imágenes, builder, tráfico). Arranque vía `uvicorn` / `run.py`. Dependencias declaradas en `pyproject.toml`. |
| **Valor**                   | Servicio API extensible, con límites claros entre capa HTTP y lógica en `app/core/`.                                                                                                                                                                                  |
| **Criterios de aceptación** | El servidor arranca y expone rutas bajo `/api`; hay tests de integración HTTP que montan la app con dependencias sustituidas (sin Docker obligatorio para la suite base).                                                                                             |


---

### 3. Backend: enrutamiento — integrar Traefik y hostname público

**Trello:** [Backend enrutamiento: integrar Traefik y agregar hostname público](https://trello.com/c/TfKrGqA3/18-backend-enrutamiento-integrar-traefik-y-agregar-hostname-publico)


| Campo                       | Descripción                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Operador de la plataforma / backend; usuario que consume workloads publicados tras el despliegue.                                                                                                                                                                                                                                                                                                                                                               |
| **Funcionalidad**           | Capa de **enrutamiento de tráfico** abstracta (`TrafficRouter`): implementación **noop** por defecto y **Traefik vía archivo dinámico JSON** (`traefik_file`). Tras desplegar un contenedor con ruta pública, se escribe la configuración y se puede señalizar recarga a Traefik (p. ej. `SIGHUP` al contenedor de Traefik cuando está configurado). Variables de entorno para dominio público, esquema `http`/`https`, red Docker y ruta del archivo dinámico. |
| **Valor**                   | Acceso HTTP(S) a servicios sin mapear puertos en el host, usando un edge proxy estándar (Traefik).                                                                                                                                                                                                                                                                                                                                                              |
| **Criterios de aceptación** | Con `VELA_TRAFFIC_ROUTER=traefik_file` y archivo + red configurados, un despliegue con `public_route` genera hostname y registro en Traefik; si el cableado de ruta falla, el contenedor se revierte para no dejar estado inconsistente (comportamiento documentado en el código de orquestación). Pruebas de integración cubren cableado de rutas con router simulado donde aplica.                                                                            |


---

### 4. Frontend: mostrar URL de acceso público tras correr contenedor

**Trello:** [Frontend: mostrar URL de acceso público tras correr container](https://trello.com/c/LxhaDWjF/19-frontend-mostrar-url-de-acceso-p%C3%BAblico-tras-correr-container)


| Campo                       | Descripción                                                                                                                                                                                                               |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Usuario de la página **Containers** que despliega un workload.                                                                                                                                                            |
| **Funcionalidad**           | Tras un `POST /api/containers/run` exitoso, si la API devuelve `public_url`, la UI muestra un **enlace clicable**, texto de éxito y botón **Copy URL** (portapapeles).                                                    |
| **Valor**                   | El usuario obtiene de inmediato el enlace para validar el despliegue en el navegador sin consultar logs ni configuración manual.                                                                                          |
| **Criterios de aceptación** | Con backend y Traefik configurados para ruta pública, al completar el formulario de ejecución aparece la URL pública; el enlace abre en nueva pestaña; copiar funciona en navegadores que permiten `clipboard.writeText`. |


---

### 5. Crear repositorio monorepo

**Trello:** [Crear repositorio monorepo](https://trello.com/c/hizd07dW/1-crear-repositorio-monorepo)


| Campo                       | Descripción                                                                                                                                                                        |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Equipo de producto / desarrollo.                                                                                                                                                   |
| **Funcionalidad**           | Un solo repositorio Git con carpetas `**backend/`** y `**frontend/`**, workflows bajo `**.github/workflows/**`, archivos de entorno de ejemplo y documentación raíz (`README.md`). |
| **Valor**                   | Unificación de versiones, CI único y clonado simple para reproducir el stack completo.                                                                                             |
| **Criterios de aceptación** | Clonar el repo y seguir el README permite trabajar en backend y frontend; la estructura de directorios coincide con la descrita en documentación del release POC.                  |


---

### 6. Setear CI en repositorio

**Trello:** [Setear CI en repositorio](https://trello.com/c/mPqk852m/7-setear-ci-en-repositorio)


| Campo                       | Descripción                                                                                                                                                                                                                                                                           |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Equipo de desarrollo; revisores de PR.                                                                                                                                                                                                                                                |
| **Funcionalidad**           | **GitHub Actions:** workflow de **pytest** en `backend/` ante cambios en backend; workflow **E2E** que instala Python, dependencias del backend, Node, Chromium y ejecuta **Playwright** ante cambios en frontend o backend. Artefacto de reporte de Playwright (retención limitada). |
| **Valor**                   | Regresiones detectadas en CI sin pasos manuales repetitivos en cada push/PR.                                                                                                                                                                                                          |
| **Criterios de aceptación** | Los workflows se disparan con los `paths` configurados; en entorno limpio, `pytest` y `npm run test:e2e` pasan en la rama/tag del release POC.                                                                                                                                        |


---

### 7. Pantalla inicial: check de conexión contra un backend

**Trello:** [Pantalla inicial: mostrar un check de conexión contra un backend](https://trello.com/c/sPmKL2rb/10-pantalla-inicial-mostrar-un-check-de-conexi%C3%B3n-contra-un-backend)


| Campo                       | Descripción                                                                                                                                                                                                                                   |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Visitante en la ruta `/` (home).                                                                                                                                                                                                              |
| **Funcionalidad**           | La página inicial llama a `getHealth()` y muestra estado **pendiente** (punto gris), **OK** (punto verde + texto del estado de la API) o **error** (punto rojo + mensaje amigable, con mensajes en español para fallos de red cuando aplica). |
| **Valor**                   | Diagnóstico inmediato de “¿el frontend ve la API?” sin herramientas externas.                                                                                                                                                                 |
| **Criterios de aceptación** | Con API arriba, se muestra éxito; con API caída o URL incorrecta, se muestra error comprensible; `aria-live` / `role="status"` para accesibilidad básica del estado.                                                                          |


---

### 8. Backend: health check para informar que está levantado

**Trello:** [Backend: health check para informar que está levantado](https://trello.com/c/Iq72hytX/11-backend-health-check-para-informar-que-est%C3%A1-levantado)


| Campo                       | Descripción                                                                                                                               |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Load balancers, orquestadores, la SPA (home), monitoreo, tests E2E.                                                                       |
| **Funcionalidad**           | Endpoint público `**GET /api/health`** que responde JSON `{"status": "ok"}` sin autenticación ni dependencia de base de datos en el POC.  |
| **Valor**                   | Señal mínima y barata para comprobar que el proceso API está vivo.                                                                        |
| **Criterios de aceptación** | `curl` o navegador a `/api/health` → 200 y cuerpo esperado; tests de integración y spec Playwright `e2e/api.spec.ts` validan el contrato. |


---

### 9. Spike: investigar bibliotecas de testeo E2E

**Trello:** [Spike: investigar bibliotecas de testeo e2e](https://trello.com/c/sk93ayqi/12-spike-investigar-bibliotecas-de-testeo-e2e)


| Campo                       | Descripción                                                                                                                                                                         |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Equipo de desarrollo / QA.                                                                                                                                                          |
| **Funcionalidad**           | Adopción de **Playwright** con `playwright.config.ts`, arranque automático de **Vite + uvicorn** en modo test, specs en `frontend/e2e/` (humo, contenedores, API real para health). |
| **Valor**                   | Automatización de flujos críticos en navegador real con mantenimiento razonable.                                                                                                    |
| **Criterios de aceptación** | Documentación en README para `npm run test:e2e`, variantes headed/UI; CI ejecuta la suite en Chromium.                                                                              |


---

### 10. Backend: implementar lógica de manejo de containers

**Trello:** [Backend: implementar lógica de manejo de containers](https://trello.com/c/WHej9Svz/4-backend-implementar-logica-de-manejo-de-containers)


| Campo                       | Descripción                                                                                                                                                                                                                                                                                                                                                                                                      |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | La API de contenedores; integraciones Docker/build; tests que validan el contrato del orquestador.                                                                                                                                                                                                                                                                                                             |
| **Funcionalidad**           | Contrato `ContainerOrchestrator` (`app/core/orchestrator.py`) e implementación **Docker** (`DockerOrchestrator`): despliegue con `DeployConfig`, arranque/parada/eliminación, comprobaciones de salud del contenedor, pull de imágenes y errores de dominio mapeados a HTTP. Orquestación alineada con **builder** (imagen vs Git) y con el **cableado de rutas** tras el deploy cuando hay `route_host`. |
| **Valor**                   | Toda la lógica de ciclo de vida queda encapsulada fuera de los handlers HTTP, facilitando tests y sustitución del proveedor.                                                                                                                                                                                                                                                                                      |
| **Criterios de aceptación** | La suite ejercita el orquestador vía rutas con **dependencias mockeadas**; existen pruebas de entorno/etiquetas donde aplica (`test_docker_orchestrator_env`, etc.). Un deploy real requiere Docker en marcha según README.                                                                                                                                                                                      |


---

### 11. Backend: listar containers y su estado

**Trello:** [Backend: listar containers y su estado](https://trello.com/c/Y8h6YoF6/17-backend-listar-containers-y-su-estado)


| Campo                       | Descripción                                                                                                                                                                                                                         |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Clientes de la API (SPA, `curl`, scripts); operadores que inspeccionan cargas.                                                                                                                                                      |
| **Funcionalidad**           | `**GET /api/containers/`** devuelve una lista de `ContainerInfo` (identificador, nombre, imagen, **estado**, puertos publicados, etiquetas, resumen de health). Query opcional **`status`** para filtrar por `ContainerStatus`.     |
| **Valor**                   | Una sola lectura coherente del inventario gestionado por Vela sin acceder al CLI de Docker.                                                                                                                                        |
| **Criterios de aceptación** | Respuesta **200** y cuerpo JSON array; caso cubierto en tests de integración (`test_list_containers` y afines); con Docker real, los estados reflejan el motor.                                                                     |


---

### 12. Backend: ejecutar contenedor desde imagen o URL vía API

**Trello:** [Backend: ejecutar container desde imagen o URL vía API](https://trello.com/c/Zbo1pxuA/16-backend-ejecutar-container-desde-imagen-o-url-via-api)


| Campo                       | Descripción                                                                                                                                                                                                                                                                                                                                                                                                  |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Actor(es)**               | Cliente de la API (en el POC, la página Containers y herramientas como `curl`).                                                                                                                                                                                                                                                                                                                              |
| **Funcionalidad**           | `**POST /api/containers/run`** acepta una **imagen Docker** o una **URL Git** (`git@`, `http(s)://`, `ssh://`); construcción/ejecución vía orquestador Docker; endpoints auxiliares de listado, start/stop/remove y comprobación de disponibilidad de imagen en registro. En el estado del tag **poc**, las rutas de contenedores **no** exigen JWT (acceso abierto al API de orquestación en ese snapshot). |
| **Valor**                   | Punto único para materializar cargas de trabajo desde fuentes habituales (imagen o repo).                                                                                                                                                                                                                                                                                                                    |
| **Criterios de aceptación** | Imagen pública válida → contenedor creado/ejecutándose según configuración; URL Git válida con Dockerfile → build y run; errores de imagen inexistente o registro devuelven respuestas controladas; tests de integración con Docker/orquestador **mockeado** cubren rutas principales.                                                                                                                       |


---

### 13. Frontend: Containers page — formulario de creación

**Trello:** [Frontend: Containers page — formulario de creación](https://trello.com/c/ee11pikM/14-frontend-containers-page-formulario-de-creacion)


| Campo                       | Descripción                                                                                                                                                                                                                                                                                                                                                                                 |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Usuario de la página **Containers**.                                                                                                                                                                                                                                                                                                                                                        |
| **Funcionalidad**           | Formulario: **imagen o URL Git**, nombre opcional, rama Git y puerto de aplicación cuando la fuente es Git (p. ej. Vite `5173`), puerto en contenedor para imágenes; validación previa de **disponibilidad de imagen** (debounce + mensajes accesibles); envío fija `**public_route: true`** y sin publicación de puerto en host en el flujo UI del POC; mensajes de éxito/error en banner. |
| **Valor**                   | Flujo guiado para desplegar sin conocer todos los detalles de Docker/Traefik manualmente.                                                                                                                                                                                                                                                                                                   |
| **Criterios de aceptación** | Campos obligatorios validados; referencia de imagen inexistente bloquea envío con mensaje claro; Git muestra campos de rama y puerto acorde al tipo de fuente; éxito dispara refresco de lista y muestra URL pública cuando corresponde (historia 4).                                                                                                                                       |


---

### 14. Frontend: Containers page — lista running workloads

**Trello:** [Frontend: Containers page — lista running workloads](https://trello.com/c/mIUipMEW/15-frontend-containers-page-lista-running-workloads)


| Campo                       | Descripción                                                                                                                                                                                                                            |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Actor(es)**               | Usuario de la página **Containers**.                                                                                                                                                                                                   |
| **Funcionalidad**           | Tabla **Running workloads** alimentada por `**GET /api/containers/`**: nombre, imagen, estado, puertos; acciones **Start**, **Stop**, **Remove**; botón **Refresh list**; estados de carga y vacío (“No Vela-managed containers yet”). |
| **Valor**                   | Visibilidad operativa de lo desplegado y control del ciclo de vida básico desde la UI.                                                                                                                                                 |
| **Criterios de aceptación** | Con contenedores gestionados por Vela en Docker, la tabla refleja datos coherentes; acciones actualizan la lista tras éxito; confirmación antes de eliminar.                                                                           |


---

## Resumen ejecutivo

### Qué se agregó o modificó en esta iteración

- **Monorepo** con backend FastAPI y frontend Vite/React, más workflows de **CI** (pytest + Playwright).
- **Salud de la API** (`GET /api/health`) y **pantalla de inicio** con indicador de conectividad.
- **Orquestación Docker** desde la API: despliegue desde **imagen** o **repositorio Git**, listado y operaciones start/stop/remove.
- **Integración Traefik** (modo archivo dinámico) para **hostnames públicos** y generación de **URL pública** mostrada en la UI tras el despliegue.
- **Comprobación de existencia de imagen** en registro antes de desplegar (con matices para errores de autenticación en registro privado documentados en API).
- **Tests**: integración HTTP con TestClient y mocks; **E2E** con Playwright, incluyendo un test contra el backend real solo para health.

### Decisiones tomadas (prioridades, diseño, riesgos)

- **Traefik vía archivo JSON** y opción de recarga por **señal al contenedor**, por limitaciones habituales de *file watch* en Docker Desktop (documentado en README).
- **CI en dos workflows** con filtros por `paths` para no ejecutar jobs innecesarios.
- **Versiones de dependencias fijadas** (política del proyecto: sin rangos `^`/`~` en dependencias clave).
- En el snapshot **poc**, la API de contenedores es **pública** (sin capa de autenticación en esas rutas); iteraciones posteriores al tag pueden añadir auth

---

