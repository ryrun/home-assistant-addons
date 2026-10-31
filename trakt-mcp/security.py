"""Native-client network filtering and Linux runtime privilege drop."""
import ipaddress
import os
from pathlib import Path

from errors import TraktError

DEFAULT_NETWORKS = ['127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16',
                    '::1/128', 'fc00::/7', 'fe80::/10']
RUNTIME_UID = RUNTIME_GID = 10001


def parse_networks(values):
    try:
        return [ipaddress.ip_network(v, strict=True) for v in values]
    except (ValueError, TypeError):
        raise TraktError('allowed_networks must contain valid CIDR networks.') from None


def client_allowed(client, networks):
    if not networks:
        return True
    try:
        address = ipaddress.ip_address(client[0])
        address = getattr(address, 'ipv4_mapped', None) or address
        return any(address in network for network in networks)
    except (ValueError, TypeError, IndexError):
        return False


def drop_privileges(data_dir):
    """The entrypoint reads Supervisor options, then drops root before serving HTTP."""
    if os.geteuid() != 0:
        return
    data_dir = Path(data_dir)
    if data_dir.is_symlink():
        raise TraktError('The data directory must not be a symbolic link.')
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chown(data_dir, RUNTIME_UID, RUNTIME_GID)
    for name in ('oauth.json', 'public-cache.sqlite3', 'public-cache.corrupt',
                 'public-cache.sqlite3-journal', 'public-cache.sqlite3-wal', 'public-cache.sqlite3-shm'):
        path = data_dir / name
        if path.is_symlink():
            raise TraktError('Persistent files must not be symbolic links.')
        if path.exists():
            os.chown(path, RUNTIME_UID, RUNTIME_GID)
            path.chmod(0o600)
    os.setgroups([])
    os.setgid(RUNTIME_GID)
    os.setuid(RUNTIME_UID)
