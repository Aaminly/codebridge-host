"""Current-user paths shared by the legacy bridge and lightweight host."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HostPaths:
    home: Path

    @classmethod
    def for_user(cls, home: Path):
        return cls(home)

    @property
    def base(self):
        return self.home / 'Library/Application Support/CodexMobile'

    @property
    def host(self):
        return self.base / 'host-v2'

    @property
    def codex(self):
        return self.home / '.codex'

    @property
    def state(self):
        return self.codex / '.codex-global-state.json'

    def prepare(self):
        self.host.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.host.chmod(0o700)


PATHS = HostPaths.for_user(Path.home())
