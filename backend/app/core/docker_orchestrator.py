from __future__ import annotations

import asyncio
import os
import re
import sys
import threading
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from typing import Any, TypeVar

import docker
import docker.errors
import requests.exceptions
from docker.types import Healthcheck

from app.core.enums import ContainerStatus, HealthStatus, RestartPolicy
from app.core.exceptions import (
    ContainerNotFoundError,
    ContainerNotRunningError,
    ImageBuildError,
    ImageNotFoundError,
    OrchestratorError,
    ProviderConnectionError,
    RegistryAccessDeniedError,
)
from app.core.models import (
    ContainerInfo,
    ContainerStats,
    DeployConfig,
    HealthCheckConfig,
    HealthResult,
    PortMapping,
)
from app.core.orchestrator import ContainerOrchestrator
from app.core.public_route_host import build_public_url

VELA_MANAGED_LABEL = "vela.managed"
VELA_MANAGED_VALUE = "true"
VELA_OWNER_LABEL = "vela.owner_id"
VELA_ROUTE_HOST_LABEL = "vela.route_host"
VELA_ROUTE_PATH_PREFIX_LABEL = "vela.route_path_prefix"
VELA_ROUTE_TLS_LABEL = "vela.route_tls"
_NS_PER_SEC = 1_000_000_000


def _max_concurrent_log_streams() -> int:
    return max(1, int(os.environ.get("VELA_MAX_LOG_STREAMS", "64")))


def _access_url_from_route_labels(labels: dict[str, Any]) -> str | None:
    host = str(labels.get(VELA_ROUTE_HOST_LABEL) or "").strip()
    if not host:
        return None
    prefix = str(labels.get(VELA_ROUTE_PATH_PREFIX_LABEL) or "/").strip()
    if not prefix.startswith("/"):
        prefix = f"/{prefix}"
    tls_raw = str(labels.get(VELA_ROUTE_TLS_LABEL) or "").lower()
    scheme = "https" if tls_raw == "true" else "http"
    return build_public_url(scheme=scheme, host=host, path_prefix=prefix)


def _is_vela_local_build_tag(image_ref: str) -> bool:
    """True for tags produced by :meth:`DockerOrchestrator.build_image` in this app."""
    return image_ref.strip().lower().startswith("vela/gitbuild:")


def _docker_daemon_unreachable_message(exc: BaseException) -> str:
    """Turn docker-py's generic connection errors into actionable text."""
    msg = str(exc).strip()
    if sys.platform == "win32" and "CreateFile" in msg and "cannot find the file" in msg.lower():
        return (
            f"{msg}\n\n"
            "Docker Engine is not reachable. On Windows, start Docker Desktop and wait until "
            "it reports that the engine is running, then try again."
        )
    if "Error while fetching server API version" in msg:
        return (
            f"{msg}\n\n"
            "The Docker daemon is not running or not installed. Start Docker (for example "
            "Docker Desktop on Windows or macOS), then retry."
        )
    return msg

T = TypeVar("T")


def _docker_restart_policy(policy: RestartPolicy) -> dict[str, Any]:
    match policy:
        case RestartPolicy.NEVER:
            return {"Name": "no", "MaximumRetryCount": 0}
        case RestartPolicy.ON_FAILURE:
            return {"Name": "on-failure", "MaximumRetryCount": 5}
        case RestartPolicy.ALWAYS:
            return {"Name": "always", "MaximumRetryCount": 0}
        case RestartPolicy.UNLESS_STOPPED:
            return {"Name": "unless-stopped", "MaximumRetryCount": 0}


def _image_pull_reference(image: str, tag: str) -> str:
    if "@" in image or re.search(r":[^/]+$", image):
        return image
    return f"{image}:{tag}"


def _docker_registry_error_text(exc: BaseException) -> str | None:
    """Short text from docker-py for registry or engine errors (for client-facing detail)."""
    if isinstance(exc, docker.errors.APIError):
        text = (getattr(exc, "explanation", None) or str(exc)).strip()
        if len(text) > 500:
            text = text[:500] + "…"
        return text or None
    message = str(exc).strip()
    return message or None


def _parse_created(created: str) -> datetime:
    if created.endswith("Z"):
        created = created[:-1] + "+00:00"
    dt = datetime.fromisoformat(created)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _map_container_status(docker_status: str) -> ContainerStatus:
    s = (docker_status or "").lower()
    match s:
        case "created":
            return ContainerStatus.CREATED
        case "running":
            return ContainerStatus.RUNNING
        case "paused":
            return ContainerStatus.PAUSED
        case "restarting":
            return ContainerStatus.RESTARTING
        case "removing" | "dead":
            return ContainerStatus.DEAD
        case "exited":
            return ContainerStatus.STOPPED
        case _:
            return ContainerStatus.UNKNOWN


def _ports_from_inspect(data: dict[str, Any]) -> list[PortMapping]:
    raw = (data.get("NetworkSettings") or {}).get("Ports") or {}
    result: list[PortMapping] = []
    for key, bindings in raw.items():
        if not bindings:
            continue
        parts = key.split("/", 1)
        cport = int(parts[0])
        proto = parts[1] if len(parts) > 1 else "tcp"
        for b in bindings:
            hp = b.get("HostPort")
            if hp is None:
                continue
            result.append(
                PortMapping(
                    host_port=int(hp),
                    container_port=cport,
                    protocol=proto,
                )
            )
    return result


def _health_status_from_docker(raw: str | None) -> HealthStatus:
    s = (raw or "").lower()
    match s:
        case "healthy":
            return HealthStatus.HEALTHY
        case "unhealthy":
            return HealthStatus.UNHEALTHY
        case "starting":
            return HealthStatus.STARTING
        case _:
            return HealthStatus.NONE


def _inspect_to_container_info(data: dict[str, Any]) -> ContainerInfo:
    cid = data.get("Id", "")
    name_raw = data.get("Name")
    if isinstance(name_raw, str) and name_raw.startswith("/"):
        name = name_raw[1:]
    else:
        names = data.get("Names") or []
        name = (names[0].lstrip("/") if names else "") or cid[:12]
    state = data.get("State") or {}
    status = _map_container_status(state.get("Status", ""))
    health_raw = (state.get("Health") or {}).get("Status")
    health = _health_status_from_docker(health_raw)

    cfg = data.get("Config") or {}
    image_ref = cfg.get("Image", "")
    labels = dict(cfg.get("Labels") or {})

    return ContainerInfo(
        id=cid,
        name=name,
        image=image_ref,
        status=status,
        created_at=_parse_created(data.get("Created", "")),
        ports=_ports_from_inspect(data),
        labels=labels,
        health=health,
        access_url=_access_url_from_route_labels(labels),
    )


def _cpu_percent_from_stats(stats: dict[str, Any]) -> float:
    cpu_stats = stats.get("cpu_stats") or {}
    precpu = stats.get("precpu_stats") or {}
    try:
        total = (cpu_stats.get("cpu_usage") or {}).get("total_usage", 0)
        pre_total = (precpu.get("cpu_usage") or {}).get("total_usage", 0)
        system = cpu_stats.get("system_cpu_usage", 0)
        pre_system = precpu.get("system_cpu_usage", 0)
        percpu = (cpu_stats.get("cpu_usage") or {}).get("percpu_usage") or []
        online = len(percpu) if percpu else int(cpu_stats.get("online_cpus") or 1)
        if online < 1:
            online = 1
        cpu_delta = total - pre_total
        system_delta = system - pre_system
        if system_delta > 0 and cpu_delta >= 0:
            return (cpu_delta / system_delta) * online * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return 0.0


def _healthcheck_for_config(cfg: HealthCheckConfig) -> Healthcheck:
    cmd = list(cfg.command)
    return Healthcheck(
        test=cmd,
        interval=cfg.interval_s * _NS_PER_SEC,
        timeout=cfg.timeout_s * _NS_PER_SEC,
        retries=cfg.retries,
        start_period=cfg.start_period_s * _NS_PER_SEC,
    )


class DockerOrchestrator(ContainerOrchestrator):
    """Docker Engine implementation of :class:`ContainerOrchestrator`."""

    def __init__(
        self,
        *,
        client: docker.DockerClient | None = None,
        default_network: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Create the orchestrator.

        Args:
            client: Optional Docker client (for tests); otherwise built from the environment.
            default_network: Attach new containers to this Docker network at create time.
                If ``None``, uses ``VELA_DOCKER_NETWORK`` from the environment when set.
                Pass ``""`` to force default engine networking even when the env var is set.
        """
        if client is not None:
            self._client = client
        else:
            try:
                self._client = docker.from_env(**kwargs)
            except docker.errors.DockerException as e:
                raise ProviderConnectionError(_docker_daemon_unreachable_message(e)) from e
        if default_network is None:
            self._default_network = os.environ.get("VELA_DOCKER_NETWORK", "").strip() or None
        else:
            self._default_network = default_network.strip() or None
        self._log_stream_semaphore = asyncio.Semaphore(_max_concurrent_log_streams())

    async def _to_thread(self, fn: Callable[[], T]) -> T:
        return await asyncio.to_thread(fn)

    def _assert_managed_labels(self, labels: dict[str, Any], container_id: str) -> None:
        if labels.get(VELA_MANAGED_LABEL) != VELA_MANAGED_VALUE:
            raise ContainerNotFoundError(container_id)

    def _merge_labels(self, config: DeployConfig) -> dict[str, str]:
        merged = {VELA_MANAGED_LABEL: VELA_MANAGED_VALUE}
        merged.update(config.labels)
        route_host = (config.route_host or "").strip()
        if route_host:
            merged[VELA_ROUTE_HOST_LABEL] = route_host.lower()
            path_prefix = (config.route_path_prefix or "/").strip() or "/"
            if not path_prefix.startswith("/"):
                path_prefix = f"/{path_prefix}"
            merged[VELA_ROUTE_PATH_PREFIX_LABEL] = path_prefix
            merged[VELA_ROUTE_TLS_LABEL] = "true" if config.route_tls else "false"
        return merged

    def _port_bindings_from_config(self, config: DeployConfig) -> dict[str, Any]:
        bindings: dict[str, Any] = {}
        for pm in config.ports:
            key = f"{pm.container_port}/{pm.protocol}"
            bindings[key] = pm.host_port
        return bindings

    def _ensure_image_sync(self, image_ref: str) -> None:
        """Resolve ``image_ref`` locally; pull from a registry only when appropriate."""
        try:
            self._client.images.get(image_ref)
        except docker.errors.ImageNotFound:
            # Local-only tags from ``docker build`` (e.g. vela/gitbuild:*) are not on a registry.
            if _is_vela_local_build_tag(image_ref):
                raise ImageNotFoundError(image_ref) from None
            try:
                self._client.images.pull(image_ref)
            except docker.errors.APIError as exc:
                if exc.status_code in (401, 403):
                    raise RegistryAccessDeniedError(
                        image_ref, registry_message=_docker_registry_error_text(exc)
                    ) from exc
                raise

    def _verify_image_reference_sync(self, image_ref: str) -> None:
        """Raise :class:`ImageNotFoundError` if ``image_ref`` is absent locally and on the registry."""
        try:
            self._client.images.get(image_ref)
        except docker.errors.ImageNotFound:
            pass
        else:
            return
        if _is_vela_local_build_tag(image_ref):
            raise ImageNotFoundError(image_ref) from None
        try:
            self._client.api.inspect_distribution(image_ref)
        except docker.errors.NotFound as exc:
            raise ImageNotFoundError(
                image_ref, registry_message=_docker_registry_error_text(exc)
            ) from exc
        except docker.errors.APIError as exc:
            if exc.status_code == 404:
                raise ImageNotFoundError(
                    image_ref, registry_message=_docker_registry_error_text(exc)
                ) from exc
            if exc.status_code in (401, 403):
                raise RegistryAccessDeniedError(
                    image_ref, registry_message=_docker_registry_error_text(exc)
                ) from exc
            raise

    def _container_env(self, config: DeployConfig) -> dict[str, str]:
        """Merge deploy env with Vite dev defaults when a Traefik ``route_host`` is set.

        Vite 6+ validates the ``Host`` header; behind Traefik the browser sends the public
        hostname. ``__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS`` appends that host to
        ``server.allowedHosts`` (see vitejs/vite#19325).
        """
        env = dict(config.env_vars)
        if "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS" in env:
            return env
        host = (config.route_host or "").strip()
        if host:
            env["__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS"] = host.lower()
        return env

    def _remove_managed_name_conflict_sync(self, name: str) -> None:
        try:
            c = self._client.containers.get(name)
        except docker.errors.NotFound:
            return
        labels = c.labels or {}
        if labels.get(VELA_MANAGED_LABEL) == VELA_MANAGED_VALUE:
            c.remove(force=True)
        else:
            msg = f"Container name already in use by a non-Vela container: {name}"
            raise OrchestratorError(msg)

    async def deploy(self, config: DeployConfig) -> ContainerInfo:
        labels = self._merge_labels(config)
        ports = self._port_bindings_from_config(config)
        restart = _docker_restart_policy(config.restart_policy)
        nano_cpus = (
            int(config.cpu_limit * _NS_PER_SEC) if config.cpu_limit is not None else None
        )
        hc = (
            _healthcheck_for_config(config.health_check)
            if config.health_check
            else None
        )

        def sync_deploy() -> ContainerInfo:
            try:
                if config.name:
                    self._remove_managed_name_conflict_sync(config.name)
                self._ensure_image_sync(config.image)
            except (OrchestratorError, docker.errors.ImageNotFound):
                raise
            except docker.errors.APIError as e:
                raise ProviderConnectionError(str(e)) from e
            except requests.exceptions.RequestException as e:
                raise ProviderConnectionError(str(e)) from e

            kwargs: dict[str, Any] = {
                "environment": self._container_env(config),
                "labels": labels,
                "ports": ports,
                "restart_policy": restart,
            }
            if config.name:
                kwargs["name"] = config.name
            if config.command is not None:
                kwargs["command"] = config.command
            if config.memory_limit is not None:
                kwargs["mem_limit"] = config.memory_limit
            if nano_cpus is not None:
                kwargs["nano_cpus"] = nano_cpus
            if hc is not None:
                kwargs["healthcheck"] = hc
            if self._default_network:
                kwargs["network"] = self._default_network

            try:
                container = self._client.containers.create(config.image, **kwargs)
                container.start()
                container.reload()
                data = container.attrs
            except docker.errors.ImageNotFound as e:
                raise ImageNotFoundError(
                    config.image, registry_message=_docker_registry_error_text(e)
                ) from e
            except docker.errors.NotFound as e:
                raise ContainerNotFoundError(str(e)) from e
            except requests.exceptions.RequestException as e:
                raise ProviderConnectionError(str(e)) from e
            except docker.errors.APIError as e:
                if e.status_code == 409 and config.name:
                    msg = f"Container name conflict: {config.name}"
                    raise OrchestratorError(msg) from e
                raise ProviderConnectionError(str(e)) from e
            except docker.errors.DockerException as e:
                raise ProviderConnectionError(str(e)) from e

            return _inspect_to_container_info(data)

        return await self._to_thread(sync_deploy)

    async def start(self, container_id: str) -> ContainerInfo:
        def sync() -> ContainerInfo:
            try:
                c = self._client.containers.get(container_id)
            except docker.errors.NotFound as e:
                raise ContainerNotFoundError(container_id) from e
            self._assert_managed_labels(c.labels or {}, container_id)
            try:
                c.start()
            except docker.errors.APIError as e:
                if e.status_code == 304:
                    pass
                else:
                    raise
            c.reload()
            return _inspect_to_container_info(c.attrs)

        try:
            return await self._to_thread(sync)
        except (ContainerNotFoundError, ProviderConnectionError):
            raise
        except requests.exceptions.RequestException as e:
            raise ProviderConnectionError(str(e)) from e
        except docker.errors.DockerException as e:
            raise ProviderConnectionError(str(e)) from e

    async def stop(self, container_id: str, *, timeout: int = 10) -> ContainerInfo:
        def sync() -> ContainerInfo:
            try:
                c = self._client.containers.get(container_id)
            except docker.errors.NotFound as e:
                raise ContainerNotFoundError(container_id) from e
            self._assert_managed_labels(c.labels or {}, container_id)
            status = (c.attrs.get("State") or {}).get("Status", "").lower()
            if status != "running":
                raise ContainerNotRunningError(container_id)
            try:
                c.stop(timeout=timeout)
            except docker.errors.APIError as e:
                if "is not running" in str(e).lower():
                    raise ContainerNotRunningError(container_id) from e
                raise
            c.reload()
            return _inspect_to_container_info(c.attrs)

        try:
            return await self._to_thread(sync)
        except (ContainerNotFoundError, ContainerNotRunningError):
            raise
        except requests.exceptions.RequestException as e:
            raise ProviderConnectionError(str(e)) from e
        except docker.errors.DockerException as e:
            raise ProviderConnectionError(str(e)) from e

    async def restart(self, container_id: str, *, timeout: int = 10) -> ContainerInfo:
        def sync() -> ContainerInfo:
            try:
                c = self._client.containers.get(container_id)
            except docker.errors.NotFound as e:
                raise ContainerNotFoundError(container_id) from e
            self._assert_managed_labels(c.labels or {}, container_id)
            c.restart(timeout=timeout)
            c.reload()
            return _inspect_to_container_info(c.attrs)

        try:
            return await self._to_thread(sync)
        except ContainerNotFoundError:
            raise
        except requests.exceptions.RequestException as e:
            raise ProviderConnectionError(str(e)) from e
        except docker.errors.DockerException as e:
            raise ProviderConnectionError(str(e)) from e

    async def remove(self, container_id: str, *, force: bool = False) -> None:
        def sync() -> None:
            try:
                c = self._client.containers.get(container_id)
            except docker.errors.NotFound as e:
                raise ContainerNotFoundError(container_id) from e
            self._assert_managed_labels(c.labels or {}, container_id)
            c.remove(force=force)

        try:
            await self._to_thread(sync)
        except ContainerNotFoundError:
            raise
        except requests.exceptions.RequestException as e:
            raise ProviderConnectionError(str(e)) from e
        except docker.errors.DockerException as e:
            raise ProviderConnectionError(str(e)) from e

    async def get(self, container_id: str) -> ContainerInfo:
        def sync() -> ContainerInfo:
            try:
                c = self._client.containers.get(container_id)
            except docker.errors.NotFound as e:
                raise ContainerNotFoundError(container_id) from e
            self._assert_managed_labels(c.labels or {}, container_id)
            return _inspect_to_container_info(c.attrs)

        try:
            return await self._to_thread(sync)
        except ContainerNotFoundError:
            raise
        except requests.exceptions.RequestException as e:
            raise ProviderConnectionError(str(e)) from e
        except docker.errors.DockerException as e:
            raise ProviderConnectionError(str(e)) from e

    async def list(
        self,
        *,
        status: ContainerStatus | None = None,
        owner_id: str | None = None,
    ) -> list[ContainerInfo]:
        label_filters = [f"{VELA_MANAGED_LABEL}={VELA_MANAGED_VALUE}"]
        if owner_id is not None:
            label_filters.append(f"{VELA_OWNER_LABEL}={owner_id}")

        def sync() -> list[ContainerInfo]:
            containers = self._client.containers.list(
                all=True,
                filters={"label": label_filters},
            )
            out: list[ContainerInfo] = []
            for c in containers:
                c.reload()
                info = _inspect_to_container_info(c.attrs)
                if status is None or info.status == status:
                    out.append(info)
            return out

        try:
            return await self._to_thread(sync)
        except requests.exceptions.RequestException as e:
            raise ProviderConnectionError(str(e)) from e
        except docker.errors.DockerException as e:
            raise ProviderConnectionError(str(e)) from e

    async def logs(self, container_id: str, *, tail: int = 100) -> str:
        def sync() -> str:
            try:
                c = self._client.containers.get(container_id)
            except docker.errors.NotFound as e:
                raise ContainerNotFoundError(container_id) from e
            self._assert_managed_labels(c.labels or {}, container_id)
            raw = c.logs(tail=tail, stdout=True, stderr=True)
            if isinstance(raw, bytes):
                return raw.decode(errors="replace")
            return str(raw)

        try:
            return await self._to_thread(sync)
        except ContainerNotFoundError:
            raise
        except requests.exceptions.RequestException as e:
            raise ProviderConnectionError(str(e)) from e
        except docker.errors.DockerException as e:
            raise ProviderConnectionError(str(e)) from e

    async def stream_logs(
        self,
        container_id: str,
        *,
        tail: int | None = 100,
        follow: bool = True,
    ) -> AsyncIterator[bytes]:
        await self._log_stream_semaphore.acquire()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=64)

        def blocking_reader() -> None:
            try:
                c = self._client.containers.get(container_id)
                self._assert_managed_labels(c.labels or {}, container_id)
                log_kwargs: dict[str, Any] = {
                    "stream": True,
                    "follow": follow,
                    "stdout": True,
                    "stderr": True,
                }
                if tail is not None:
                    log_kwargs["tail"] = tail
                stream = c.logs(**log_kwargs)
                for chunk in stream:
                    if not chunk:
                        continue
                    payload = bytes(chunk)
                    fut = asyncio.run_coroutine_threadsafe(
                        queue.put(("chunk", payload)),
                        loop,
                    )
                    fut.result(timeout=120)
                fut_done = asyncio.run_coroutine_threadsafe(
                    queue.put(("done", None)),
                    loop,
                )
                fut_done.result(timeout=30)
            except BaseException as exc:
                fut_err = asyncio.run_coroutine_threadsafe(
                    queue.put(("err", exc)),
                    loop,
                )
                try:
                    fut_err.result(timeout=30)
                except BaseException:
                    pass

        thread = threading.Thread(
            target=blocking_reader,
            name="vela-docker-log-stream",
            daemon=True,
        )
        thread.start()
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "chunk":
                    yield payload
                elif kind == "done":
                    break
                elif kind == "err":
                    exc = payload
                    if isinstance(exc, docker.errors.NotFound):
                        raise ContainerNotFoundError(container_id) from exc
                    if isinstance(exc, requests.exceptions.RequestException):
                        raise ProviderConnectionError(str(exc)) from exc
                    if isinstance(exc, docker.errors.DockerException):
                        raise ProviderConnectionError(str(exc)) from exc
                    raise exc
        finally:
            self._log_stream_semaphore.release()

    async def get_stats(self, container_id: str) -> ContainerStats:
        def sync() -> ContainerStats:
            try:
                c = self._client.containers.get(container_id)
            except docker.errors.NotFound as e:
                raise ContainerNotFoundError(container_id) from e
            self._assert_managed_labels(c.labels or {}, container_id)
            stats = c.stats(stream=False)
            mem = stats.get("memory_stats") or {}
            usage = int(mem.get("usage", 0))
            limit = int(mem.get("limit", 0))
            mem_pct = (usage / limit * 100.0) if limit else 0.0
            rx = 0
            tx = 0
            for iface in (stats.get("networks") or {}).values():
                rx += int(iface.get("rx_bytes", 0))
                tx += int(iface.get("tx_bytes", 0))
            now = datetime.now(timezone.utc)
            return ContainerStats(
                container_id=c.id,
                timestamp=now,
                cpu_percent=_cpu_percent_from_stats(stats),
                memory_usage_bytes=usage,
                memory_limit_bytes=limit,
                memory_percent=mem_pct,
                network_rx_bytes=rx,
                network_tx_bytes=tx,
            )

        try:
            return await self._to_thread(sync)
        except ContainerNotFoundError:
            raise
        except requests.exceptions.RequestException as e:
            raise ProviderConnectionError(str(e)) from e
        except docker.errors.DockerException as e:
            raise ProviderConnectionError(str(e)) from e

    async def get_health(self, container_id: str) -> HealthResult:
        def sync() -> HealthResult:
            try:
                c = self._client.containers.get(container_id)
            except docker.errors.NotFound as e:
                raise ContainerNotFoundError(container_id) from e
            self._assert_managed_labels(c.labels or {}, container_id)
            data = c.attrs
            state = data.get("State") or {}
            health = state.get("Health")
            now = datetime.now(timezone.utc)
            if not health:
                return HealthResult(
                    status=HealthStatus.NONE,
                    timestamp=now,
                    output=None,
                    exit_code=None,
                )
            status = _health_status_from_docker(health.get("Status"))
            log = health.get("Log") or []
            last = log[-1] if log else {}
            out = last.get("Output")
            if isinstance(out, bytes):
                out = out.decode(errors="replace")
            exit_code = last.get("ExitCode")
            if exit_code is not None:
                exit_code = int(exit_code)
            end = last.get("End")
            ts = now
            if isinstance(end, str) and end:
                try:
                    ts = _parse_created(end)
                except ValueError:
                    ts = now
            return HealthResult(
                status=status,
                timestamp=ts,
                output=out,
                exit_code=exit_code,
            )

        try:
            return await self._to_thread(sync)
        except ContainerNotFoundError:
            raise
        except requests.exceptions.RequestException as e:
            raise ProviderConnectionError(str(e)) from e
        except docker.errors.DockerException as e:
            raise ProviderConnectionError(str(e)) from e

    async def pull_image(self, image: str, *, tag: str = "latest") -> None:
        ref = _image_pull_reference(image, tag)

        def sync() -> None:
            self._client.images.pull(ref)

        try:
            await self._to_thread(sync)
        except docker.errors.ImageNotFound as e:
            raise ImageNotFoundError(
                ref, registry_message=_docker_registry_error_text(e)
            ) from e
        except docker.errors.APIError as exc:
            if exc.status_code in (401, 403):
                raise RegistryAccessDeniedError(
                    ref, registry_message=_docker_registry_error_text(exc)
                ) from exc
            raise ProviderConnectionError(str(exc)) from exc
        except requests.exceptions.RequestException as e:
            raise ProviderConnectionError(str(e)) from e
        except docker.errors.DockerException as e:
            raise ProviderConnectionError(str(e)) from e

    async def verify_image_reference_available(self, image_ref: str) -> None:
        def sync() -> None:
            try:
                self._verify_image_reference_sync(image_ref.strip())
            except ImageNotFoundError:
                raise
            except RegistryAccessDeniedError:
                raise
            except docker.errors.APIError as exc:
                raise ProviderConnectionError(str(exc)) from exc
            except requests.exceptions.RequestException as exc:
                raise ProviderConnectionError(str(exc)) from exc

        try:
            await self._to_thread(sync)
        except ImageNotFoundError:
            raise
        except RegistryAccessDeniedError:
            raise
        except ProviderConnectionError:
            raise
        except docker.errors.DockerException as exc:
            raise ProviderConnectionError(str(exc)) from exc

    async def build_image(
        self, path: str, *, tag: str, dockerfile: str = "Dockerfile"
    ) -> str:
        def sync() -> str:
            log_parts: list[str] = []
            image_obj = None
            try:
                # decode=False: ImageCollection.build() always runs json_stream() on the
                # API stream; decode=True yields dicts and breaks json_stream (dict has no decode).
                image_obj, build_logs = self._client.images.build(
                    path=path,
                    tag=tag,
                    dockerfile=dockerfile,
                    rm=True,
                    decode=False,
                )
            except docker.errors.BuildError as e:
                log = getattr(e, "build_log", None) or []
                for chunk in log:
                    if isinstance(chunk, dict) and "stream" in chunk:
                        log_parts.append(str(chunk["stream"]))
                raise ImageBuildError(str(e), build_log="".join(log_parts)) from e
            except docker.errors.APIError as e:
                raise ImageBuildError(str(e), build_log="".join(log_parts)) from e

            for chunk in build_logs:
                if not isinstance(chunk, dict):
                    continue
                if "stream" in chunk:
                    log_parts.append(str(chunk["stream"]))
                if "error" in chunk:
                    msg = str(chunk["error"])
                    raise ImageBuildError(msg, build_log="".join(log_parts))
                aux = chunk.get("aux")
                if isinstance(aux, dict) and "ID" in aux:
                    image_obj = self._client.images.get(aux["ID"])

            if image_obj is None:
                try:
                    image_obj = self._client.images.get(tag)
                except docker.errors.ImageNotFound as e:
                    raise ImageBuildError(
                        "Build finished but image could not be resolved",
                        build_log="".join(log_parts),
                    ) from e

            return image_obj.id

        try:
            return await self._to_thread(sync)
        except ImageBuildError:
            raise
        except requests.exceptions.RequestException as e:
            raise ProviderConnectionError(str(e)) from e
        except docker.errors.DockerException as e:
            raise ProviderConnectionError(str(e)) from e

    async def list_images(self) -> list[str]:
        def sync() -> list[str]:
            tags: list[str] = []
            for img in self._client.images.list():
                tags.extend(img.tags or [])
            return sorted(set(tags))

        try:
            return await self._to_thread(sync)
        except requests.exceptions.RequestException as e:
            raise ProviderConnectionError(str(e)) from e
        except docker.errors.DockerException as e:
            raise ProviderConnectionError(str(e)) from e
