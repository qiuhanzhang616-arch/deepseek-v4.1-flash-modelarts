"""ModelArts A2 W4A8 launcher with a narrow clone3 errno compatibility filter.

The inherited seccomp policy remains active. This adds a filter that still
denies clone3, but returns ENOSYS so glibc 2.38 can fall back to the already
permitted legacy clone syscall. The filter is inherited by the model launcher.
"""

import ctypes
import errno
import os
import platform
import threading


AUDIT_ARCH_AARCH64 = 0xC00000B7
SYS_CLONE3 = 435
PR_SET_NO_NEW_PRIVS = 38
PR_SET_SECCOMP = 22
SECCOMP_MODE_FILTER = 2
SECCOMP_RET_ALLOW = 0x7FFF0000
SECCOMP_RET_ERRNO = 0x00050000

BPF_LD = 0x00
BPF_W = 0x00
BPF_ABS = 0x20
BPF_JMP = 0x05
BPF_JEQ = 0x10
BPF_K = 0x00
BPF_RET = 0x06

START_SCRIPT = "/model/w4a8/startup/start_modelarts_single_replica.c4-clone3-otel-stderr.sh"
OVERRIDES = "/model/w4a8/startup/runtime-overrides-c5-nospec.env"


class SockFilter(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("k", ctypes.c_uint),
    ]


class SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(SockFilter))]


def fail(message):
    raise SystemExit(f"[CLONE3-COMPAT][ERROR] {message}")


def log(*values):
    print("[CLONE3-COMPAT]", *values, flush=True)


if platform.machine() not in ("aarch64", "arm64"):
    fail(f"unexpected architecture {platform.machine()}")
if not os.path.isfile(START_SCRIPT):
    fail(f"startup script missing: {START_SCRIPT}")
if not os.path.isfile(OVERRIDES):
    fail(f"runtime overrides missing: {OVERRIDES}")

libc = ctypes.CDLL(None, use_errno=True)
libc.prctl.restype = ctypes.c_int
libc.prctl.argtypes = [
    ctypes.c_int,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
]
libc.syscall.restype = ctypes.c_long


def clone3_errno():
    ctypes.set_errno(0)
    result = libc.syscall(
        ctypes.c_long(SYS_CLONE3), ctypes.c_void_p(0), ctypes.c_size_t(88)
    )
    return result, ctypes.get_errno()


before_result, before_errno = clone3_errno()
log("before_clone3", before_result, before_errno)
if (before_result, before_errno) != (-1, errno.EPERM):
    fail("expected inherited clone3 EPERM was not observed")

# seccomp_data.arch is at offset 4; seccomp_data.nr is at offset 0.
# This additive filter leaves every inherited seccomp rule in force.
filter_bytes = (SockFilter * 6)(
    SockFilter(BPF_LD | BPF_W | BPF_ABS, 0, 0, 4),
    SockFilter(BPF_JMP | BPF_JEQ | BPF_K, 0, 3, AUDIT_ARCH_AARCH64),
    SockFilter(BPF_LD | BPF_W | BPF_ABS, 0, 0, 0),
    SockFilter(BPF_JMP | BPF_JEQ | BPF_K, 0, 1, SYS_CLONE3),
    SockFilter(BPF_RET | BPF_K, 0, 0, SECCOMP_RET_ERRNO | errno.ENOSYS),
    SockFilter(BPF_RET | BPF_K, 0, 0, SECCOMP_RET_ALLOW),
)
program = SockFprog(len(filter_bytes), filter_bytes)

ctypes.set_errno(0)
if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
    fail(f"PR_SET_NO_NEW_PRIVS failed with errno {ctypes.get_errno()}")

ctypes.set_errno(0)
if libc.prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ctypes.addressof(program), 0, 0) != 0:
    fail(f"PR_SET_SECCOMP failed with errno {ctypes.get_errno()}")

after_result, after_errno = clone3_errno()
log("after_clone3", after_result, after_errno)
if (after_result, after_errno) != (-1, errno.ENOSYS):
    fail("clone3 did not return ENOSYS after the additive filter")

worker = threading.Thread(target=lambda: None)
worker.start()
worker.join(timeout=5)
if worker.is_alive():
    fail("thread creation probe timed out")
log("thread_probe", "passed")

environment = os.environ.copy()
environment["RUNTIME_OVERRIDE_FILE"] = OVERRIDES
log("exec", START_SCRIPT)
os.execve("/bin/bash", ["/bin/bash", START_SCRIPT], environment)
