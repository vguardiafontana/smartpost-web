import argparse
from datetime import datetime
import gc
import json
import logging
import os
from pathlib import Path
import statistics
import sys
import time

p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);p.add_argument('--repeats',type=int,default=3);a=p.parse_args()
root=Path(a.root).resolve();out=Path(a.out).resolve();out.mkdir(parents=True,exist_ok=True)
os.environ['SMARTPOST_DATA_DIR']=str(out/'userdata');sys.path.insert(0,str(root))
from app.core.config import load_config
from app.core.models import RunContext
from app.core.state import StateDB
from app.procesamiento.processor import process_batch
from app.visitas.excel import convert_visits_csv_to_xlsx
cfg=load_config();cfg['reportes']['cache_enabled']=False
cfg['paths']['reports']=str(out/'reports');cfg['paths']['dry_run_reports']=str(out/'dry')
run=RunContext('bench',datetime(2026,10,8),out/'work')
source=Path(__file__).parent/'before/visits.csv'
logger=logging.getLogger('com-bench');logger.addHandler(logging.NullHandler())
state=StateDB(out/'state.db');result={}
def measure(name,fn):
    values=[];last=None
    for _ in range(a.repeats):
        gc.collect();t=time.perf_counter();last=fn();values.append(time.perf_counter()-t)
        print(name,values[-1],flush=True)
    result[name]={'seconds':values,'median':statistics.median(values),'result':last}
try:
    measure('desktop_report_batch_500',lambda:process_batch(cfg,run,state,[source],{'ZETABURGOS'},logger))
    measure('desktop_visits_500',lambda:convert_visits_csv_to_xlsx(cfg,run,source,logger))
finally:state.close()
(out/'timings.json').write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
print('DONE',flush=True)
