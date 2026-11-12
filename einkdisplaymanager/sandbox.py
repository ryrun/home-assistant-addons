"""Fail-closed OS restrictions installed after imports and before any user source."""

import ctypes
import errno
import os
import resource
import socket
import sys


def restrict():
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
            raise RuntimeError("Cannot disable privilege escalation.")
        seccomp = ctypes.CDLL("libseccomp.so.2", use_errno=True)
        seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
        seccomp.seccomp_init.restype = ctypes.c_void_p
        seccomp.seccomp_rule_add.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
        seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
        seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
        context = seccomp.seccomp_init(0x00050000 | errno.EPERM)
        if not context:
            raise RuntimeError("Cannot create syscall filter.")
        try:
            # No path access, sockets, process creation/inspection, or execution.
            for name in (
                "read",
                "write",
                "close",
                "fstat",
                "lseek",
                "mmap",
                "mprotect",
                "munmap",
                "brk",
                "rt_sigaction",
                "rt_sigprocmask",
                "rt_sigreturn",
                "sigaltstack",
                "futex",
                "getpid",
                "gettid",
                "clock_gettime",
                "gettimeofday",
                "time",
                "getrandom",
                "exit",
                "exit_group",
                "madvise",
                "sched_yield",
                "fcntl",
            ):
                number = seccomp.seccomp_syscall_resolve_name(name.encode())
                if (
                    number >= 0
                    and seccomp.seccomp_rule_add(context, 0x7FFF0000, number, 0) != 0
                ):
                    raise RuntimeError("Cannot install syscall rule.")
            if seccomp.seccomp_load(context) != 0:
                raise RuntimeError("Cannot load syscall filter.")
        finally:
            seccomp.seccomp_release(context)
        return "linux-seccomp"
    if sys.platform == "darwin":
        library = ctypes.CDLL("/usr/lib/libsandbox.dylib", use_errno=True)
        library.sandbox_init.argtypes = [
            ctypes.c_char_p,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_char_p),
        ]
        error = ctypes.c_char_p()
        profile = b"(version 1)(allow default)(deny file-read*)(deny file-write*)(deny network*)(deny process-exec)(deny process-fork)(deny mach-lookup)(deny process-info*)"
        if library.sandbox_init(profile, 0, ctypes.byref(error)) != 0:
            raise RuntimeError("Cannot install development sandbox.")
        return "macos-seatbelt"
    raise RuntimeError("No supported process sandbox on this platform.")


def probe():
    def network():
        with socket.socket() as connection:
            connection.connect(("127.0.0.1", 9))

    failures = []
    for name, operation in (
        ("files", lambda: os.open("/etc/passwd", os.O_RDONLY)),
        (
            "writes",
            lambda: os.open("/tmp/eink-sandbox-probe", os.O_CREAT | os.O_WRONLY, 0o600),
        ),
        ("network", network),
        ("processes", lambda: os.fork()),
    ):
        try:
            result = operation()
        except OSError as error:
            if error.errno in (errno.EPERM, errno.EACCES):
                continue
            failures.append(name)
            continue
        if isinstance(result, int) and name in ("files", "writes"):
            os.close(result)
        if name == "processes" and result == 0:
            os._exit(1)
        failures.append(name)
    if failures:
        raise RuntimeError("Isolation verification failed.")
