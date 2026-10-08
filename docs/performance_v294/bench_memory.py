"""Pico de memoria de un proceso nuevo, sólo generación local de XLSX."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import time

p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);p.add_argument('--fixture',required=True);a=p.parse_args()
root=Path(a.root).resolve();out=Path(a.out).resolve();out.mkdir(parents=True,exist_ok=True)
os.environ['SMARTPOST_DATA_DIR']=str(out/'userdata');sys.path.insert(0,str(root))
from app.procesamiento.io_sources import read_csv_file,rows_to_dicts
from app.procesamiento.rules import normalize_row
from app.reportes.portable_report import write_report_portable
headers,raw=read_csv_file(Path(a.fixture))
mapped,_=rows_to_dicts(headers,raw)
rows=[normalize_row(r)[0] for r in mapped]
t=time.perf_counter()
write_report_portable(root/'assets/TEMPLATE_REPORTE.xlsx',out/'report.xlsx',rows,'ZETABURGOS',{})
elapsed=time.perf_counter()-t
class Counters(ctypes.Structure):
    _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=wintypes.HANDLE
psapi=ctypes.WinDLL('psapi');psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
info=Counters();info.cb=ctypes.sizeof(info)
assert psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(info),info.cb)
print(json.dumps({'seconds':elapsed,'peak_working_set_bytes':info.PeakWorkingSetSize}))
