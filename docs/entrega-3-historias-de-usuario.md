# Documentación de entrega — iteración 3: alertas por email y modo equipo (Vela)

> A continuación presentamos la documentación que vamos a exigirles en cada entrega.

**Ámbito de código:** commit `f1fe8ee` en el repositorio [LorenzoFerraces/Vela](https://github.com/LorenzoFerraces/Vela) (rama `f/user-groups`; sin tag de release publicado al redactar).

## User stories

### 1. Monitoreo de contenedores y alertas por email configurables

**Trello:** [Monitoreo de contenedores y detección de fallos o parada inesperada](https://trello.com/c/P7TylkVy/53-monitoreo-de-contenedores-y-detecci%C3%B3n-de-fallos-o-parada-inesperada) · [Envío de alertas por email ante fallo o cierre inesperado de contenedor](https://trello.com/c/lLe58vrW/54-env%C3%ADo-de-alertas-por-email-ante-fallo-o-cierre-inesperado-de-contenedor) · [Preferencias de notificación por email y antiduplicado de alertas](https://trello.com/c/Y5ZAirXV/55-preferencias-de-notificaci%C3%B3n-por-email-y-antiduplicado-de-alertas) · [Configuración de notificaciones por email en settings (API y UI)](https://trello.com/c/pLWwGpNl/56-configuraci%C3%B3n-de-notificaciones-por-email-en-settings-api-y-ui)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Persona con cuenta en Vela que despliega contenedores y quiere enterarse a tiempo cuando algo deja de funcionar bien, sin revisar el panel todo el día. |
| **Funcionalidad** | Vela vigila en segundo plano los contenedores del usuario. Si un contenedor se detiene, falla, pasa a estado poco saludable o desaparece de forma inesperada, la plataforma puede avisar por correo al dueño del despliegue. El aviso incluye el nombre del contenedor, el tipo de incidente, la hora y, cuando hay trazas disponibles, un archivo adjunto con los logs recientes para facilitar el diagnóstico. En **Settings**, la tarjeta **Email Alerts** permite activar o desactivar las alertas, ver el correo de la cuenta (solo lectura) y elegir qué tipos de incidente interesan: **Container stopped**, **Container failed** y **Container unhealthy**. Las alertas se envían en el momento en que se detecta el problema. También se puede consultar un historial reciente de alertas enviadas desde la misma tarjeta. Si el mismo incidente se repite en poco tiempo, no se saturará la bandeja con correos duplicados del mismo evento. |
| **Valor** | El usuario puede confiar en que Vela le avisará cuando algo vaya mal, con control sobre qué eventos le importan y sin tener que mirar el Dashboard de forma continua. |
| **Criterios de aceptación** | Con las alertas activadas en Settings, un contenedor que deja de estar sano genera un correo al email de la cuenta cuando el tipo de incidente está marcado en las preferencias. Desactivar **Enable email alerts** o desmarcar un tipo concreto impide ese aviso. Tras guardar cambios en Settings, al recargar la página las preferencias siguen como se dejaron. El historial **Show recent alerts** muestra alertas recientes o un mensaje claro si aún no hubo ninguna. Ante el mismo contenedor y el mismo tipo de incidente en un intervalo corto, llega como máximo un correo por ventana de antiduplicado. |

---

### 2. Modo equipo: proyectos compartidos, roles y colaboración

**Trello:** [Modelo PostgreSQL y API de membresías, organizaciones, proyectos y roles](https://trello.com/c/cT3bioO2/57-modelo-postgresql-y-api-de-membres%C3%ADas-organizaciones-proyectos-y-roles) · [RBAC por proyecto en API de contenedores (viewer / operator)](https://trello.com/c/O5HsgQtM/58-rbac-por-proyecto-en-api-de-contenedores-viewer-operator) · [Historial de deploy compartido por proyecto](https://trello.com/c/exQGoqji/59-historial-de-deploy-compartido-por-proyecto) · [Settings: configuración de equipo e invitaciones](https://trello.com/c/XcQ5bBqO/60-settings-configuraci%C3%B3n-de-equipo-e-invitaciones)

| Campo | Descripción |
|--------|-------------|
| **Actor(es)** | Usuario autenticado que trabaja solo o en equipo; dueño de un equipo que invita y administra miembros; invitado que acepta o rechaza unirse; miembro que abandona un equipo del que no es dueño. |
| **Funcionalidad** | Cada cuenta tiene un **Personal workspace** privado, visible en la página **Teams** del menú principal. Desde ahí se pueden **crear equipos** adicionales, ver la lista de equipos a los que se pertenece y abrir el detalle de cada uno. El dueño invita por correo y asigna rol **Viewer** u **Operator**. La invitación no da acceso hasta que la persona la **acepta** en la sección **Incoming invitations**; también puede **rechazarla**. El dueño puede cancelar invitaciones pendientes, cambiar el rol de un miembro o quitarlo del equipo. Quien no es dueño puede **Leave team** y perderá acceso a los workloads de ese equipo. En **Containers** y **Dashboard**, los miembros ven los contenedores de los equipos a los que pertenecen: un **Viewer** puede consultar estado, URL de acceso y logs, pero no iniciar, detener ni eliminar cargas; un **Operator** sí puede operarlas; el **Owner** además gestiona el equipo. En la página **Containers**, la sección **Deploy history** muestra despliegues del proyecto personal y de los equipos compartidos, con autor y posibilidad de comparar versiones. La gestión de equipos vive en **Teams**; **Settings** sigue reservado para cuenta, integraciones y alertas por email. |
| **Valor** | Varias personas pueden compartir workloads y el historial de despliegues con permisos claros, sin mezclar recursos entre equipos y sin acceso hasta que el invitado lo acepte explícitamente. |
| **Criterios de aceptación** | Tras registrarse, el usuario ve su **Personal workspace** en Teams. Crear un equipo lo añade a la lista y permite invitar miembros. Un invitado no aparece como miembro ni ve contenedores del equipo hasta pulsar **Accept**; **Reject** descarta la invitación. Un **Viewer** ve workloads del equipo pero las acciones de arranque, parada y eliminación aparecen deshabilitadas con un mensaje de permisos insuficientes. Un **Operator** puede iniciar y detener contenedores del equipo. Un usuario que no pertenece a un equipo no ve sus contenedores. El historial de deploy en Containers incluye entradas de equipos compartidos cuando el usuario es miembro. El dueño puede cambiar roles, eliminar miembros y cancelar invitaciones pendientes; un miembro no dueño puede abandonar el equipo tras confirmación. |

---

## Resumen ejecutivo

### Qué se entregó en esta iteración

- **Vigilancia automática** de contenedores: la plataforma detecta paradas, fallos, mala salud y desapariciones inesperadas sin intervención del usuario.
- **Alertas por email** configurables desde Settings, con tipos de incidente a elegir, envío inmediato y adjunto de logs cuando corresponde.
- **Historial de alertas** consultable desde la misma tarjeta de Email Alerts.
- **Trabajo en equipo** con espacio personal, equipos compartidos, invitaciones con aceptación explícita y roles Viewer / Operator / Owner.
- **Página Teams** para crear equipos, invitar, aceptar invitaciones y administrar miembros.
- **Permisos en workloads** alineados al rol: observación para viewers, operación para operators y owners.
- **Historial de deploy compartido** visible para miembros del proyecto en Containers.

### Decisiones tomadas (prioridades, diseño, riesgos)

- **Invitaciones opt-in:** nadie entra al equipo hasta aceptar; el dueño puede cancelar invitaciones pendientes.
- **Espacio personal** automático por cuenta; los equipos adicionales son espacios compartidos con nombre propio.
- **Tres roles iniciales:** Owner (administra el equipo), Operator (ve y opera contenedores), Viewer (solo consulta).
- **Teams separado de Settings:** colaboración en **Teams**; preferencias personales, integraciones y alertas en **Settings**.
- **Frecuencia de alertas:** en esta iteración solo hay envío inmediato; resúmenes diarios o semanales quedan fuera de alcance por ahora.
- **Tarjeta Trello “Settings: configuración de equipo”:** la gestión de equipos se entregó en la página **Teams**, no como sección dentro de Settings.

---

## Consejos

- Redactar **criterios de aceptación** como escenarios que un revisor pueda recorrer en la app (Settings, Teams, Containers, bandeja de correo), no como detalle de implementación.
- Agrupar tarjetas Trello de frontend y backend en **una historia de usuario** cuando describen el mismo resultado para quien usa el producto.
- Enlazar tarjetas bajo **Trello:** dentro de cada historia, sin repetir el mismo relato por cada tarjeta mecánica.
