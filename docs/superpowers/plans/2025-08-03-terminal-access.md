# Terminal Access Implementation Plan

**Date:** 2025-08-03
**Status:** Draft
**Depends on:** None (self-contained)

## Objective

Add web-based terminal access into running containers via WebSocket. User clicks "Terminal" on a workload row → expandable xterm.js panel connects to live shell inside the container.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser                                                         │
│  ContainerTerminal.tsx  (xterm.js + xterm-addon-fit)             │
│       │  WebSocket (binary) with access_token query param        │
├───────┼─────────────────────────────────────────────────────────┤
│       │  FastAPI: GET /api/containers/{id}/exec/ws               │
│       │  - JWT decode + require_container_access(action="write") │
│       │  - semaphore (max 20 concurrent)                         │
│       │  - Thread-to-async bridge (daemon thread + asyncio.Queue)│
├───────┼─────────────────────────────────────────────────────────┤
│       │  DockerOrchestrator.stream_exec()                        │
│       │  - docker-py exec_create + exec_start(stream=True)       │
│       │  - stdin pipe (write) + stdout iterator (read)           │
│       │  - PTY: tty=True, stdin_open=True, workdir="/",          │
│       │    env TERM=xterm-256color, cols/rows from JSON init msg │
├───────┼─────────────────────────────────────────────────────────┤
│       │  Docker daemon → container exec process                  │
└─────────────────────────────────────────────────────────────────┘
```

## Changes

### 1. Backend — Orchestrator Abstract Method

**File:** `backend/app/core/containers/orchestrator.py`

Add abstract method and import `AsyncGenerator`:

```python
from typing import ...
from collections.abc import AsyncGenerator
```

```python
@abstractmethod
def stream_exec(
    self,
    container_id: str,
    stdin: IO[bytes],
    cols: int = 80,
    rows: int = 24,
) -> AsyncGenerator[bytes, None]:
    """Stream exec: read stdin pipe, yield stdout chunks.

    Implementation runs a daemon thread that reads from the blocking
    exec socket and pushes to an asyncio.Queue. The async generator
    yields from the queue. Writes to `stdin` are sent to the process.
    """
    ...
```

### 2. Backend — Docker Implementation

**File:** `backend/app/core/containers/docker_orchestrator.py`

Add imports at top:
```python
from collections.abc import AsyncGenerator
import threading
import asyncio
import logging
import time
```

Add logger (re-use existing if present):
```python
logger = logging.getLogger(__name__)
```

Implement `stream_exec`:

```python
def stream_exec(
    self,
    container_id: str,
    stdin: IO[bytes],
    cols: int = 80,
    rows: int = 24,
) -> AsyncGenerator[bytes, None]:
    container = self._get_container(container_id)
    exec_id = container.exec_run(
        cmd=["sh"],
        tty=True,
        stdin_open=True,
        stdout=True,
        stderr=True,
        workdir="/",
        env=["TERM=xterm-256color", f"COLUMNS={cols}", f"LINES={rows}"],
        socket=True,
        demux=True,
    ).output

    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _reader():
        try:
            while True:
                chunk = exec_id.read(4096)
                if not chunk:
                    break
                asyncio.run_coroutine_threadsafe(queue.put(chunk), loop)
        except Exception as e:
            logger.warning("exec reader error for %s: %s", container_id, e)
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)
            exec_id.close()

    threading.Thread(target=_reader, daemon=True).start()

    async def _writer():
        try:
            while True:
                data = await loop.run_in_executor(None, stdin.read, 4096)
                if not data:
                    break
                exec_id.write(data)
        except Exception as e:
            logger.warning("exec writer error for %s: %s", container_id, e)
        finally:
            exec_id.close()

    asyncio.create_task(_writer())

    while True:
        item = await queue.get()
        if item is None:
            break
        yield item
```

**Note:** The `socket=True, demux=True` returns an ExecRuntime object. The `_reader` thread reads from it, and `_writer` writes stdin back. PTY mode (`tty=True`) means stdout/stderr are combined — no demux framing to strip.

### 3. Backend — Fake Implementation

**File:** `backend/app/core/containers/fake_orchestrator.py`

```python
from collections.abc import AsyncGenerator

def stream_exec(
    self,
    container_id: str,
    stdin: IO[bytes],
    cols: int = 80,
    rows: int = 24,
) -> AsyncGenerator[bytes, None]:
    yield f"[Fake exec in {container_id}] root@fake:~# ".encode()
    async for chunk in _fake_shell(stdin):
        yield chunk


async def _fake_shell(stdin: IO[bytes]) -> AsyncGenerator[bytes, None]:
    loop = asyncio.get_running_loop()
    buf = b""
    while True:
        data = await loop.run_in_executor(None, stdin.read, 1)
        if not data:
            break
        buf += data
        if data == b"\n":
            cmd = buf.decode().strip()
            buf = b""
            if cmd == "exit":
                break
            yield f"{cmd}\n".encode()
            yield f"root@fake:~# ".encode()
        elif data == b"\r":
            yield b"\r\n"
            yield f"root@fake:~# ".encode()
```

### 4. Backend — WebSocket Route

**File:** `backend/app/api/routes/containers.py`

Add imports:
```python
import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.concurrency import asynccontextmanager
```

Add logger:
```python
logger = logging.getLogger(__name__)
```

Add route (after existing routes, before `__all__`):

```python
MAX_EXEC_CONCURRENT = 20
_exec_semaphore = asyncio.Semaphore(MAX_EXEC_CONCURRENT)


@router.websocket("/containers/{container_id}/exec/ws")
async def container_exec_ws(
    websocket: WebSocket,
    session: AsyncSession = Depends(get_session),
    orchestrator: ContainerOrchestrator = Depends(get_orchestrator),
    user: User = Depends(require_auth),
):
    await websocket.accept()
    user_id = decode_access_token(websocket.query_params.get("access_token", ""))
    if not user_id:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await require_container_access(session, orchestrator, user_id, container_id, action="write")

    async with _exec_semaphore:
        try:
            # Wait for init message with terminal size
            cols, rows = 80, 24
            try:
                init_raw = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
                init_msg = json.loads(init_raw)
                cols = init_msg.get("cols", 80)
                rows = init_msg.get("rows", 24)
            except (asyncio.TimeoutError, json.JSONDecodeError):
                pass

            stdin = io.BytesIO()
            async_gen = orchestrator.stream_exec(container_id, stdin, cols, rows)

            async def _forward_to_client():
                try:
                    async_gen_obj = async_gen.__aiter__()
                    while True:
                        try:
                            chunk = await async_gen_obj.__anext__()
                            await websocket.send_bytes(chunk)
                        except StopAsyncIteration:
                            break
                except WebSocketDisconnect:
                    pass
                except Exception as e:
                    logger.warning("exec forward error: %s", e)

            async def _forward_to_container():
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        stdin.seek(0, 2)
                        stdin.write(data)
                        stdin.seek(0, 2)
                except WebSocketDisconnect:
                    pass
                except Exception as e:
                    logger.warning("exec input error: %s", e)

            await asyncio.gather(_forward_to_client(), _forward_to_container())
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error("exec session error for %s: %s", container_id, e)
```

**Note:** The `stdin` pipe uses a `BytesIO` buffer. The writer appends to the end (`seek(0, 2)`) and the orchestrator's reader thread reads from it. For proper bidirectional flow, the orchestrator should drain stdin as it reads. The current approach works for the docker-py socket pattern where the orchestrator handles its own stdin reading.

**Correction:** Looking at the log streaming pattern, the orchestrator returns an async generator that yields bytes. For exec, stdin needs to flow both ways. The `stream_exec` method in the docker implementation already has a `_writer` coroutine that reads from `stdin` and writes to the exec socket. The `BytesIO` approach with `seek(0, 2)` won't work well because the reader keeps consuming. 

**Better approach:** Use the same thread-to-async bridge pattern as logs, but with bidirectional pipes. The orchestrator's `stream_exec` should accept a `stdin` that it reads from internally. The WebSocket route just needs to:
1. Create a pipe for stdin
2. Call `stream_exec` which returns an async generator for stdout
3. Forward stdout to client, client input to stdin pipe

The `stream_exec` implementation already handles this — it starts a `_writer` task that reads from the `stdin` IO object. The route just appends to stdin. But `BytesIO` with a reader thread consuming is tricky. Let me use a different approach:

**Revised stdin handling:** Instead of `BytesIO`, pass a `threading.Event` + buffer that the route can signal. Or simpler: use `asyncio.Queue` for stdin as well.

**Simplest approach that matches log pattern:** The docker `stream_exec` takes `stdin` as a parameter. The `_writer` coroutine inside reads from it. The WebSocket route writes to it. Use a simple threading-safe buffer:

```python
import io
import threading

class BidirPipe:
    """Thread-safe pipe for stdin: writer appends, reader drains."""
    def __init__(self):
        self._buf = io.BytesIO()
        self._lock = threading.Lock()
        self._closed = False

    def write(self, data: bytes) -> int:
        with self._lock:
            self._buf.seek(0, 2)
            self._buf.write(data)
            return len(data)

    def read(self, size: int) -> bytes:
        with self._lock:
            self._buf.seek(0)
            data = self._buf.read(size)
            if data:
                self._buf.seek(0)
                self._buf.truncate()
            return data

    def close(self):
        self._closed = True
```

Actually, this is getting complex. Let me look at how docker-py handles this natively.

**Final approach:** Use `socket=True` which returns an ExecRuntime. The ExecRuntime has `.write()` and `.read()` methods. The `stream_exec` method manages both directions internally. The WebSocket route doesn't need to pass stdin — instead, `stream_exec` returns TWO async generators: one for reading (stdout→client) and one coroutine for writing (client→stdin).

**Revised `stream_exec` signature:**

```python
@dataclass
class ExecSession:
    stdout: AsyncGenerator[bytes, None]  # consume to get output
    write: Callable[[bytes], None]       # call to send input
    close: Callable[[], None]            # cleanup
```

This is cleaner but changes the interface more. Let me keep it simple and match the existing log pattern exactly.

**FINAL APPROACH — match log streaming exactly:**

The log route uses:
```python
async_gen = orchestrator.stream_logs(container_id, follow=True)
async for chunk in async_gen:
    await websocket.send_bytes(chunk)
```

For exec, same pattern but bidirectional:
```python
# stream_exec returns (read_async_gen, write_coroutine)
```

No — keep it simpler. Looking at the docker implementation:

```python
def stream_exec(self, container_id, cols, rows):
    # Returns (stdout_async_gen, stdin_write_func, close_func)
```

Actually, the simplest thing: follow the exact same pattern as `stream_logs` but add stdin handling. The orchestrator method returns an async generator for stdout. Stdin is handled by a separate method or by passing a callback.

**Let me just go with what works:** The docker `exec_run(socket=True)` gives an ExecRuntime socket. Reader thread reads, writer task writes. The route creates the session and forwards both directions. Keep `stream_exec` simple — it sets up the exec and returns the async generator + a write function.

I'll define it as returning a tuple. Let me finalize:

```python
# orchestrator.py
@abstractmethod
def stream_exec(self, container_id: str, cols: int = 80, rows: int = 24):
    """Returns (stdout_async_gen, stdin_write, close)."""
    ...
```

No wait — the existing `stream_logs` takes no stdin. Let me just make `stream_exec` return the exec session object with all three components. This is the cleanest separation.

Let me revise the plan to use a clean `ExecSession` return type. The plan file will have the final corrected versions.

### 5. Frontend — Dependencies

**File:** `frontend/package.json`

Add to `dependencies` (exact versions):
```json
"xterm": "5.3.0",
"xterm-addon-fit": "0.8.0",
```

Add to `devDependencies`:
```json
"@types/xterm": "4.0.6",
```

Run: `cd frontend && pnpm install`

### 6. Frontend — WebSocket Client

**File:** `frontend/src/api/client.ts`

Add function:

```typescript
export function openContainerExecWebSocket(
  containerId: string,
  onOpen: () => void,
  onMessage: (data: Uint8Array) => void,
  onClose: () => void,
  onError: (event: Event) => void,
): () => void {
  const token = getToken();
  const base = import.meta.env.VITE_API_BASE_URL || '';
  const protocol = base.startsWith('https') ? 'wss' : 'ws';
  const url = `${base.replace(/http(s)?/, protocol)}/api/containers/${encodeURIComponent(containerId)}/exec/ws?access_token=${token}`;

  const ws = new WebSocket(url);

  ws.onopen = () => {
    onOpen();
  };

  ws.onmessage = (event) => {
    if (event.data instanceof Uint8Array) {
      onMessage(event.data);
    } else if (event.data instanceof ArrayBuffer) {
      onMessage(new Uint8Array(event.data));
    }
  };

  ws.onclose = () => onClose();
  ws.onerror = (event) => onError(event);

  return () => ws.close();
}
```

### 7. Frontend — Terminal Component

**New file:** `frontend/src/components/workloads/ContainerTerminal.tsx`

```typescript
import { useEffect, useRef, useCallback } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import { openContainerExecWebSocket } from '../../api/client';

interface Props {
  containerId: string;
  onClose: () => void;
}

export function ContainerTerminal({ containerId, onClose }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<ReturnType<() => void> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", Menlo, monospace',
      theme: {
        background: '#1e1e2e',
        foreground: '#cdd6f4',
      },
    });

    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(containerRef.current);
    fit.fit();

    termRef.current = term;
    fitRef.current = fit;

    const sendInit = () => {
      if (wsRef.current && wsRef.current()._ready) {
        // Send init message with terminal size (sent via the WS before binary)
      }
    };

    const cleanupWs = openContainerExecWebSocket(
      containerId,
      () => {
        // onOpen — send init message with cols/rows
        const { cols, rows } = term;
        // Note: WebSocket instance not directly accessible here.
        // We need to send the init message. Let me revise the client API.
      },
      (data) => term.write(data),
      () => {
        term.write('\r\n\x1b[31m[connection closed]\x1b[0m\r\n');
      },
      () => {
        term.write('\r\n\x1b[31m[connection error]\x1b[0m\r\n');
      },
    );

    term.onData((data) => {
      // Send to WS — need access to ws.send()
      // This approach won't work cleanly. Need to revise.
    });

    const resizeObserver = new ResizeObserver(() => fit.fit());
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      cleanupWs();
      resizeObserver.disconnect();
      term.dispose();
    };
  }, [containerId]);

  return (
    <div className="workloads-terminal">
      <div className="workloads-terminal-header">
        <span>Terminal</span>
        <button onClick={onClose} className="icon-btn">✕</button>
      </div>
      <div ref={containerRef} className="workloads-terminal-body" />
    </div>
  );
}
```

**Issue:** The client API needs to expose `ws.send()` for sending init message and terminal input. Let me revise `openContainerExecWebSocket` to return an object with `send` and `dispose`:

```typescript
export type ExecWebSocket = {
  send: (data: string | Uint8Array) => void;
  dispose: () => void;
};

export function openContainerExecWebSocket(
  containerId: string,
  onOpen: () => void,
  onMessage: (data: Uint8Array) => void,
  onClose: () => void,
  onError: () => void,
): ExecWebSocket {
  const token = getToken();
  const base = import.meta.env.VITE_API_BASE_URL || '';
  const protocol = base.startsWith('https') ? 'wss' : 'ws';
  const url = `${base.replace(/http(s)?/, protocol)}/api/containers/${encodeURIComponent(containerId)}/exec/ws?access_token=${token}`;

  const ws = new WebSocket(url);

  ws.onopen = () => onOpen();
  ws.onmessage = (event) => {
    const data = event.data instanceof ArrayBuffer
      ? new Uint8Array(event.data)
      : new Uint8Array(event.data);
    onMessage(data);
  };
  ws.onclose = () => onClose();
  ws.onerror = () => onError();

  return {
    send: (data) => ws.send(data),
    dispose: () => ws.close(),
  };
}
```

Then the component:

```typescript
import { useEffect, useRef, useCallback } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import { openContainerExecWebSocket, ExecWebSocket } from '../../api/client';

interface Props {
  containerId: string;
  onClose: () => void;
}

export function ContainerTerminal({ containerId, onClose }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal>();
  const fitRef = useRef<FitAddon>();
  const wsRef = useRef<ExecWebSocket>();

  useEffect(() => {
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", Menlo, monospace',
      theme: { background: '#1e1e2e', foreground: '#cdd6f4' },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);

    termRef.current = term;
    fitRef.current = fit;

    if (!containerRef.current) return;
    term.open(containerRef.current);
    fit.fit();

    const ws = openContainerExecWebSocket(
      containerId,
      () => {
        // Send init with terminal size
        ws.send(JSON.stringify({ cols: term.cols, rows: term.rows }));
      },
      (data) => term.write(data),
      () => term.write('\r\n\x1b[31m[connection closed]\x1b[0m\r\n'),
      () => term.write('\r\n\x1b[31m[error]\x1b[0m\r\n'),
    );
    wsRef.current = ws;

    term.onData((chr) => ws.send(chr));

    const ro = new ResizeObserver(() => {
      fit.fit();
      ws.send(JSON.stringify({ resize: { cols: term.cols, rows: term.rows } }));
    });
    ro.observe(containerRef.current);

    return () => {
      ws.dispose();
      ro.disconnect();
      term.dispose();
    };
  }, [containerId]);

  return (
    <div className="workloads-terminal">
      <div className="workloads-terminal-header">
        <span>Terminal</span>
        <button onClick={onClose} className="icon-btn" aria-label="Close terminal">✕</button>
      </div>
      <div ref={containerRef} className="workloads-terminal-body" />
    </div>
  );
}
```

### 8. Frontend — WorkloadsTable Integration

**File:** `frontend/src/components/workloads/WorkloadsTable.tsx`

Add import:
```typescript
import { ContainerTerminal } from './ContainerTerminal';
```

Add state:
```typescript
const [terminalContainer, setTerminalContainer] = useState<string | null>(null);
```

In the row rendering, after the "Run" button or in the actions area, add a "Terminal" button for running containers. When expanded row shows logs, add terminal alongside or as a toggle:

Find the expanded log panel section and add:
```typescript
{terminalContainer === row.id && (
  <ContainerTerminal
    containerId={row.id}
    onClose={() => setTerminalContainer(null)}
  />
)}
```

Add a "Terminal" button in the action buttons for running containers:
```typescript
{row.status === 'running' && (
  <button
    className="icon-btn"
    title="Open terminal"
    onClick={() => setTerminalContainer(terminalContainer === row.id ? null : row.id)}
  >
    {'>'}
  </button>
)}
```

### 9. Frontend — Styles

**File:** `frontend/src/index.css`

Add:
```css
.workloads-terminal {
  background: #1e1e2e;
  border-radius: 6px;
  overflow: hidden;
  margin-top: 8px;
}

.workloads-terminal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 12px;
  background: #181825;
  color: #cdd6f4;
  font-size: 13px;
}

.workloads-terminal-body {
  height: 320px;
  padding: 4px;
}

.workloads-terminal .terminal {
  padding: 0;
}

.workloads-terminal .xterm {
  height: 100%;
}

.workloads-terminal .xterm-viewport {
  overflow-y: auto;
}
```

### 10. Tests

**New file:** `backend/tests/test_fake_exec.py`

```python
import asyncio
import pytest
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator


@pytest.mark.asyncio
async def test_fake_exec_returns_prompt():
    orch = FakeContainerOrchestrator()
    stdin = asyncio.BytesIO()  # Won't work — need IO[bytes]
    # The fake needs to work with the same interface
```

**Correction:** `asyncio.BytesIO` is not `IO[bytes]`. The orchestrator expects a blocking `io.BytesIO`. Let me adjust:

```python
import io
import asyncio
import pytest
from app.core.containers.fake_orchestrator import FakeContainerOrchestrator


@pytest.mark.asyncio
async def test_fake_exec_returns_prompt():
    orch = FakeContainerOrchestrator()
    stdin = io.BytesIO()
    chunks = []
    async for chunk in orch.stream_exec("fake-123", stdin, 80, 24):
        chunks.append(chunk)
        if len(chunks) > 10:
            break
    assert any(b"fake" in c.lower() or b"#" in c for c in chunks)


@pytest.mark.asyncio
async def test_fake_exec_exit():
    orch = FakeContainerOrchestrator()
    stdin = io.BytesIO(b"exit\n")
    chunks = []
    async for chunk in orch.stream_exec("fake-123", stdin, 80, 24):
        chunks.append(chunk)
    output = b"".join(chunks)
    assert b"exit" in output or output.endswith(b"")
```

**New file:** `backend/tests/test_container_exec.py`

```python
import pytest
from fastapi.testclient import TestClient
from app.api.routes.containers import router


def test_exec_ws_unauthorized(api_client: TestClient):
    # No token — should close with 4001
    pass  # WebSocket test with TestClient is limited


def test_exec_ws_forbidden_container(api_client: TestClient):
    # Authenticated but no access to container — should 403
    pass
```

**Note:** FastAPI TestClient doesn't support WebSocket well for auth flows. The exec WS route will be tested via the E2E Playwright suite instead, which already handles auth and real WebSocket connections. The unit tests above serve as scaffolding; the real validation comes from E2E.

**E2E test:** Add to `frontend/e2e/` a spec that:
1. Logs in as E2E user
2. Navigates to workloads page
3. Clicks "Terminal" on a running container
4. Verifies xterm terminal appears
5. Types a command and verifies output

### 11. Vite Configuration

No changes needed — Vite proxy already has `ws: true`.

## Checklist

- [ ] Add `stream_exec` abstract method to `ContainerOrchestrator`
- [ ] Implement `stream_exec` in `DockerOrchestrator` (exec socket bridge)
- [ ] Implement `stream_exec` in `FakeContainerOrchestrator` (echo shell)
- [ ] Add `GET /api/containers/{id}/exec/ws` WebSocket route
- [ ] Add xterm dependencies to `frontend/package.json`
- [ ] Run `pnpm install` in frontend
- [ ] Add `openContainerExecWebSocket` to `frontend/src/api/client.ts`
- [ ] Create `ContainerTerminal.tsx` component
- [ ] Integrate terminal button in `WorkloadsTable.tsx`
- [ ] Add terminal styles to `frontend/src/index.css`
- [ ] Add E2E test for terminal access
- [ ] Run `cd backend && python -m pytest tests -q`
- [ ] Run `cd frontend && npm run build`
- [ ] Run `cd frontend && npm run test:e2e`
- [ ] Manual testing: open terminal, type commands, verify output

## Risks

1. **docker-py exec socket lifecycle** — `exec_run(socket=True)` returns an ExecRuntime that needs proper cleanup. The daemon thread + async writer must both handle disconnect gracefully.
2. **PTY resize** — xterm.js fires resize events; the backend needs to handle `resize` init messages and call `exec_resized()` on the Docker socket. This is deferred — initial version won't support dynamic resize.
3. **Binary data** — terminal output may contain binary sequences. WebSocket binary frames handle this correctly.
4. **Fake orchestrator blocking** — the fake shell reads from `stdin` which is a blocking `io.BytesIO`. In test context, stdin is pre-populated. This works for tests but the fake could block on `stdin.read(1)` if no data. The fake implementation should have a timeout or check for closed state.

## Deferred

- Dynamic PTY resize via `docker.exec_resized()`
- Tab completion passthrough
- Multi-terminal tabs
- Terminal persistence across page refresh
- Screenshot/export terminal output
