#!/usr/bin/env python3
"""Narrow clone3 ENOSYS compatibility launcher for the pinned A2 image.

The inherited seccomp restrictions stay active. Returning ENOSYS for clone3
lets glibc use the permitted legacy clone syscall, as in the validated C5
W4A8 service. This process then execs exactly the supplied command.
"""

import ctypes
import errno
import os
import platform
import sys
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
    raise SystemExit(f"[pd][clone3-compat][ERROR] {message}")


def main():
    if platform.machine() not in ("aarch64", "arm64"):
        fail(f"unexpected architecture {platform.machine()}")
    if len(sys.argv) < 2:
        fail("missing command to exec")

    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.restype = ctypes.c_int
    libc.prctl.argtypes = [
        ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong
    ]
    libc.syscall.restype = ctypes.c_long

    def clone3_errno():
        ctypes.set_errno(0)
        result = libc.syscall(
            ctypes.c_long(SYS_CLONE3), ctypes.c_void_p(0), ctypes.c_size_t(88)
        )
        return result, ctypes.get_errno()

    before = clone3_errno()
    print("[pd][clone3-compat] before", before, flush=True)
    if before != (-1, errno.EPERM):
        fail(f"expected inherited clone3 EPERM, got {before}")

    # seccomp_data.arch offset 4; seccomp_data.nr offset 0. Every syscall
    # except AArch64 clone3 returns ALLOW from this *additional* filter.
    filters = (SockFilter * 6)(
        SockFilter(BPF_LD | BPF_W | BPF_ABS, 0, 0, 4),
        SockFilter(BPF_JMP | BPF_JEQ | BPF_K, 0, 3, AUDIT_ARCH_AARCH64),
        SockFilter(BPF_LD | BPF_W | BPF_ABS, 0, 0, 0),
        SockFilter(BPF_JMP | BPF_JEQ | BPF_K, 0, 1, SYS_CLONE3),
        SockFilter(BPF_RET | BPF_K, 0, 0, SECCOMP_RET_ERRNO | errno.ENOSYS),
        SockFilter(BPF_RET | BPF_K, 0, 0, SECCOMP_RET_ALLOW),
    )
    program = SockFprog(len(filters), filters)
    ctypes.set_errno(0)
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        fail(f"PR_SET_NO_NEW_PRIVS errno={ctypes.get_errno()}")
    ctypes.set_errno(0)
    if libc.prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ctypes.addressof(program), 0, 0) != 0:
        fail(f"PR_SET_SECCOMP errno={ctypes.get_errno()}")
    after = clone3_errno()
    print("[pd][clone3-compat] after", after, flush=True)
    if after != (-1, errno.ENOSYS):
        fail(f"expected clone3 ENOSYS, got {after}")

    worker = threading.Thread(target=lambda: None)
    worker.start()
    worker.join(timeout=5)
    if worker.is_alive():
        fail("thread probe timed out")
    print("[pd][clone3-compat] thread probe passed; exec", sys.argv[1], flush=True)
    child_env = os.environ.copy()
    child_env["PD_CLONE3_COMPAT_READY"] = "1"
    child_env.update(OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
    os.execvpe(sys.argv[1], sys.argv[1:], child_env)


if __name__ == "__main__":
    main()
