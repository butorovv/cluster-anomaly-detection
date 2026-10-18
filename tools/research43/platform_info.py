"""Read-only host metadata for reproducible research timing reports."""
import os
import platform
import sys


def collect():
    cpu=platform.processor();ram=None
    if sys.platform=='win32':
        import ctypes
        import winreg
        from ctypes import wintypes
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
                cpu=winreg.QueryValueEx(key,'ProcessorNameString')[0]
        except OSError:
            pass
        class Memory(ctypes.Structure):
            _fields_=[('length',wintypes.DWORD),('load',wintypes.DWORD)]+[(name,ctypes.c_ulonglong) for name in
                ['total_physical','available_physical','total_page','available_page','total_virtual','available_virtual','extended']]
        value=Memory();value.length=ctypes.sizeof(value)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):ram=int(value.total_physical)
    else:
        try:ram=os.sysconf('SC_PHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')
        except (ValueError,OSError,AttributeError):pass
    return dict(cpu=cpu or 'unavailable',logical_processors=os.cpu_count(),RAM_bytes=ram,
                note='read-only registry/WinAPI or platform/sysconf; missing values remain unavailable')
