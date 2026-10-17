"""One interactive WinWhisperPlus process per Windows user, across builds."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os


class _ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


def _kernel():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
        function.restype = wintypes.BOOL
    return kernel


def _processes():
    kernel = _kernel()
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        result = {}
        more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            result[entry.th32ProcessID] = (entry.szExeFile.casefold(), entry.th32ParentProcessID)
            more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(ctypes.get_last_error())
        return result
    finally:
        kernel.CloseHandle(snapshot)


def _process_identity(pid):
    import win32api
    import win32process
    import win32security
    # Limited query rights work for both normal and elevated processes owned
    # by the same user. All handles are non-inheritable and short-lived.
    process = win32api.OpenProcess(0x1000, False, pid)
    try:
        token = win32security.OpenProcessToken(process, 0x0008)  # TOKEN_QUERY
        try:
            sid = win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token, 1)[0])
        finally:
            token.Close()
        created = win32process.GetProcessTimes(process)["CreationTime"].timestamp()
        return sid, created
    finally:
        process.Close()


def _legacy_instance_running(sid):
    """Also recognize older frozen EXEs without a mutex.

    Ignore our own PyInstaller bootloader and all ancestors. Only earlier
    launches count, so two simultaneous new launches cannot reject each other.
    The named mutex is the authoritative gate between updated versions.
    """
    processes = _processes()
    pid = os.getpid()
    ancestors = {pid}
    root = pid
    current_name = processes.get(pid, ("", 0))[0]
    parent = processes.get(pid, ("", 0))[1]
    while parent in processes and parent not in ancestors:
        ancestors.add(parent)
        name, next_parent = processes[parent]
        if current_name == "winwhisperplus.exe" and name == current_name:
            root = parent
        else:
            current_name = ""  # only the contiguous bootloader chain
        parent = next_parent
    _, started = _process_identity(root)
    for candidate, (name, _) in processes.items():
        if name != "winwhisperplus.exe" or candidate in ancestors:
            continue
        try:
            owner, created = _process_identity(candidate)
        except Exception:
            # Exited processes and processes owned by other users may be
            # inaccessible. They must not prevent this user's application.
            continue
        if owner == sid and (created, candidate) < (started, root):
            return True
    return False


class SingleInstance:
    def __init__(self, name=None, *, detect_legacy=True):
        self.name = name
        self.detect_legacy = detect_legacy
        self._handle = None
        self._kernel = _kernel()

    def acquire(self):
        if self._handle is not None:
            return True
        sid, _ = _process_identity(os.getpid())
        name = self.name or f"Global\\WinWhisperPlus.Application.{sid}"
        ctypes.set_last_error(0)
        handle = self._kernel.CreateMutexW(None, False, name)
        error = ctypes.get_last_error()
        if not handle:
            if error == 5:  # existing elevated instance denies full mutex access
                return False
            raise ctypes.WinError(error)
        if error == 183:  # ERROR_ALREADY_EXISTS
            self._kernel.CloseHandle(handle)
            return False
        self._handle = handle
        try:
            if self.detect_legacy and _legacy_instance_running(sid):
                self.close()
                return False
        except Exception:
            self.close()
            raise
        return True

    def close(self):
        if self._handle is not None:
            self._kernel.CloseHandle(self._handle)
            self._handle = None
