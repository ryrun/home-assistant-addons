"""Prepare only this add-on's data directory, then relinquish root privileges."""

import os
from pathlib import Path


def main():
    os.umask(0o077)
    root = Path('/data')
    root.mkdir(mode=0o700, exist_ok=True)
    if os.getuid() == 0:
        for parent, dirs, files in os.walk(root, followlinks=False):
            for path in [Path(parent), *(Path(parent) / n for n in dirs + files)]:
                if not path.is_symlink():
                    os.chown(path, 10002, 10002)
        os.setgroups([])
        os.setgid(10002)
        os.setuid(10002)
    os.execvp('python', ['python', '/app/server.py'])


if __name__ == '__main__':
    main()
