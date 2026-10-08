"""Mediciones locales repetibles, sin servicios externos ni datos reales."""
import argparse
import csv
import gc
import hashlib
import json
import logging
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import zipfile
from datetime import datetime

parser = argparse.ArgumentParser()
parser.add_argument('--root', required=True)
parser.add_argument('--out', required=True)
parser.add_argument('--repeats', type=int, default=5)
parser.add_argument('--startup', choices=['desktop', 'web'])
args = parser.parse_args()
root = Path(args.root).resolve(); out = Path(args.out).resolve(); out.mkdir(parents=True, exist_ok=True)
os.environ['SMARTPOST_DATA_DIR'] = str(out/'userdata')
os.environ['DATABASE_URL'] = ''
os.environ['SMARTPOST_WEB_PIN'] = '246810'
os.environ['SMARTPOST_WEB_SESSION_SECRET'] = 'benchmark-only-' + 'x'*64
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(root))

if args.startup:
    start = time.perf_counter()
    if args.startup == 'desktop':
        from PySide6.QtWidgets import QApplication
        from app.gui.main_window import MainWindow
        application = QApplication([])
        MainWindow._first_run_if_needed = lambda self: None
        window = MainWindow(); window.show(); application.processEvents()
    else:
        from app.web.server import app
    print(json.dumps({'seconds': time.perf_counter()-start}))
    sys.exit(0)

from app.procesamiento.rules import EXPECTED_HEADERS, normalize_row, resolve_seller_from_rows, normalize_key
from app.procesamiento.io_sources import rows_to_dicts, read_csv_file
from app.core.config import load_config, build_alias_map
from app.core.models import RunContext
from app.reportes.portable_report import write_report_portable
from app.visitas.portable_excel import convert_visits_csv_to_xlsx_portable
from app.web.report_jobs import _FileReportStore

logger = logging.getLogger('bench'); logger.addHandler(logging.NullHandler())
cfg = load_config(); cfg['paths']['reports'] = str(out/'visits')
headers = list(EXPECTED_HEADERS)
raw = []
for i in range(5000):
    row = {h: '' for h in headers}
    row.update({'Nro Guia': str(6200000+i), 'Cliente':'ZETABURGOS SRL', 'Remito': ['001234', '#ABC', '470123456', 'ABC001', '2000018857041302'][i%5],
                'Servicio': 'FLEX', 'Estado': ['1RVT - 1° VISITA', 'ENTREGADO', 'REPROGRAMACIÓN'][i%3],
                'Fecha':'08/10/2026 19:20:30', 'Fecha Ingreso a Planta':'2026-10-08 15:00:00',
                'FECHA ULTIMO ESTADO':'08/10/2026 19:20:30', 'Documento':'34.072273', 'COM.CELULAR':'011123456',
                'Destinatario':f'Prueba {i}', 'Domicilio':'Calle 123\nPiso 2', 'Peso':'1,25', 'CP':'1875'})
    raw.append([row[h] for h in headers])
csv_path=out/'fixture.csv'
with csv_path.open('w', newline='', encoding='utf-8') as file:
    writer=csv.writer(file, delimiter=';');writer.writerow(headers);writer.writerows(raw)
mapped,_=rows_to_dicts(headers,raw)
normalized=[normalize_row(r)[0] for r in mapped[:500]]
aliases=build_alias_map(cfg,normalize_key)
run=RunContext('bench',datetime(2026,10,8),out/'work')
report=out/'report.xlsx'
store=_FileReportStore(out/'store')
result={}

def measure(name,fn):
    samples=[]
    for _ in range(args.repeats):
        gc.collect(); start=time.perf_counter(); fn(); samples.append(time.perf_counter()-start)
    result[name]={'seconds':samples,'median':statistics.median(samples)}
    print(name,round(result[name]['median'],6),flush=True)

for kind in ['desktop','web']:
    samples=[]
    for _ in range(args.repeats):
        p=subprocess.run([sys.executable,__file__,'--root',str(root),'--out',str(out/'startup'), '--startup',kind],capture_output=True,text=True,check=True)
        samples.append(json.loads(p.stdout.strip().splitlines()[-1])['seconds'])
    result['startup_'+kind]={'seconds':samples,'median':statistics.median(samples)}
    print('startup_'+kind,round(statistics.median(samples),6),flush=True)
measure('config_read',load_config)
measure('csv_read_5000',lambda:read_csv_file(csv_path))
measure('map_headers_5000',lambda:rows_to_dicts(headers,raw))
measure('seller_5000',lambda:resolve_seller_from_rows(mapped,aliases))
measure('normalize_5000',lambda:[normalize_row(row) for row in mapped])
measure('report_web_500',lambda:write_report_portable(root/'assets/TEMPLATE_REPORTE.xlsx',report,normalized,'ZETABURGOS',{}))
# VISITAS: 500 filas, 75 columnas con los mismos textos.
visits_csv=out/'visits.csv'
with visits_csv.open('w',newline='',encoding='utf-8') as file:
    writer=csv.writer(file,delimiter=';');writer.writerow(headers);writer.writerows(raw[:500])
measure('visits_web_500',lambda:convert_visits_csv_to_xlsx_portable(cfg,run,visits_csv,logger))
def bundle():
    with zipfile.ZipFile(out/'bundle.zip','w',zipfile.ZIP_DEFLATED) as z:
        for i in range(20):z.write(report,f'SELLER {i}.xlsx')
measure('zip_20_reports',bundle)
data=(out/'bundle.zip').read_bytes();meta={'id':'artifact'}
measure('storage_local',lambda:store.put_artifact('job',meta,data))
measure('download_local_read',lambda:store.get_artifact('job','artifact'))
result['fixture']={'sha256':hashlib.sha256(csv_path.read_bytes()).hexdigest(),'rows':5000,'report_rows':500,'python':sys.version,'platform':sys.platform,'repeats':args.repeats}
(out/'timings.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print('DONE',flush=True)
