"""Makes sure ffmpeg and Tesseract never outlive battle-marker.

On Windows the app puts itself into a job object that kills every process
in it when the job's last handle closes. Only this process holds that
handle, so when it ends for any reason, a crash, Task Manager or a normal
exit, Windows ends every ffmpeg and Tesseract it started. Child processes
join the job automatically when they start.

A normal exit also kills tracked processes directly, which covers other
systems where no job object exists.
"""

import atexit
import subprocess
import sys
import threading

_job = None  # kept for the lifetime of the process, closing it would kill the children
_tracked: set[subprocess.Popen] = set()
_lock = threading.Lock()

# Without this a console window flashes for every child started from the window.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def contain_children() -> bool:
    """Ties every child process to this one. Call once at startup. True when it worked."""
    global _job
    if _job is not None:
        return True
    if sys.platform != "win32":
        return False
    try:
        _job = _create_kill_on_close_job()
    except OSError as e:
        print(f"battle-marker: child processes are not tied to the app ({e})", file=sys.stderr)
        return False
    return True


def track(proc: subprocess.Popen) -> None:
    with _lock:
        _tracked.add(proc)


def untrack(proc: subprocess.Popen) -> None:
    with _lock:
        _tracked.discard(proc)


@atexit.register
def _kill_tracked() -> None:
    with _lock:
        procs = list(_tracked)
    for proc in procs:
        if proc.poll() is None:
            proc.kill()


def _create_kill_on_close_job():
    import ctypes
    from ctypes import wintypes

    job_object_extended_limit_information = 9
    job_object_limit_kill_on_job_close = 0x2000

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = ExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = job_object_limit_kill_on_job_close
    if not kernel32.SetInformationJobObject(
        job, job_object_extended_limit_information, ctypes.byref(info), ctypes.sizeof(info),
    ):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel32.CloseHandle(job)
        raise error
    if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel32.CloseHandle(job)
        raise error
    return job
