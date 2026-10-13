"""Read-only discovery. A reachable socket alone does not prove desktop ownership."""
import asyncio
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from websockets.asyncio.client import unix_connect
from websockets.exceptions import WebSocketException


@dataclass(frozen=True)
class Endpoint:
    socket_path: Path


@dataclass(frozen=True)
class ProbeResult:
    endpoint: Endpoint
    version: str
    loaded_thread_ids: frozenset[str]
    error: str | None = None


def discover(home: Path) -> list[Endpoint]:
    paths = [home / '.codex/app-server-control/app-server-control.sock',
             home / 'Library/Application Support/CodexMobile/desktop.sock']
    endpoints = [Endpoint(path) for path in paths if path.is_socket()]
    base = paths[1].parent
    if (base / 'host-v2/desktop.json').exists():
        try:
            owner = json.loads((base / 'desktop-owner.json').read_text())
            os.kill(owner['pid'], 0)
            parent = subprocess.run(['/bin/ps','-p',str(owner['pid']),'-o','ppid='],capture_output=True,text=True,check=True)
            if int(parent.stdout.strip()) != owner['parentPid']:raise ValueError('Desktop detached')
            app = subprocess.run(['/bin/ps','-p',str(owner['parentPid']),'-o','comm='],capture_output=True,text=True,check=True)
            if not app.stdout.strip().startswith(owner['app']+'/'):raise ValueError('Desktop changed')
        except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):
            endpoints = [e for e in endpoints if e.socket_path != paths[1]]
    return endpoints


async def probe(endpoint: Endpoint) -> ProbeResult:
    try:
        async with asyncio.timeout(10):
            async with unix_connect(str(endpoint.socket_path), open_timeout=3,
                                    max_size=32 * 1024 * 1024) as ws:
                sequence = 0

                async def rpc(method, params):
                    nonlocal sequence
                    sequence += 1
                    await ws.send(json.dumps({'id': sequence, 'method': method, 'params': params}))
                    while True:
                        response = json.loads(await ws.recv())
                        if not isinstance(response, dict):
                            raise ValueError('Invalid RPC envelope')
                        if response.get('id') != sequence:
                            continue
                        if 'error' in response or not isinstance(response.get('result'), dict):
                            raise ValueError('Read-only RPC rejected')
                        return response['result']

                result = await rpc('initialize', {
                    'clientInfo': {'name': 'codebridge-discovery', 'version': '2'},
                    'capabilities': {'experimentalApi': True}})
                version = result.get('userAgent')
                if not isinstance(version, str):
                    raise ValueError('Missing server version')
                await ws.send(json.dumps({'method': 'initialized'}))
                cursor, cursors, loaded = None, set(), set()
                for _ in range(100):
                    page = await rpc('thread/loaded/list', {'cursor': cursor, 'limit': 100})
                    data = page.get('data')
                    if not isinstance(data, list) or any(not isinstance(x, str) for x in data):
                        raise ValueError('Invalid loaded thread list')
                    loaded.update(data)
                    cursor = page.get('nextCursor')
                    if cursor is None:
                        return ProbeResult(endpoint, version, frozenset(loaded))
                    if not isinstance(cursor, str) or cursor in cursors:
                        raise ValueError('Invalid pagination cursor')
                    cursors.add(cursor)
                raise ValueError('Loaded thread pagination exceeds limit')
    except (OSError, TimeoutError, ValueError, WebSocketException) as error:
        return ProbeResult(endpoint, '', frozenset(), type(error).__name__)


def choose(results: list[ProbeResult], expected_thread_id: str | None) -> ProbeResult:
    matches = [result for result in results if result.error is None and
               (expected_thread_id is None or expected_thread_id in result.loaded_thread_ids)]
    if len(matches) != 1:
        raise ValueError('Desktop instance is missing or ambiguous')
    return matches[0]
