from __future__ import annotations

import json
import os
import queue
import re
import threading
import traceback
import uuid
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import load_config, resolve_path


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class _FileReportStore:
    def __init__(self, root: Path):
        self.root = root; self.root.mkdir(parents=True, exist_ok=True)
        self.art_root = self.root / "artifacts"; self.art_root.mkdir(exist_ok=True)
    def _job(self, job_id): return self.root / f"{re.sub(r'[^a-fA-F0-9]', '', job_id)}.json"
    def get(self, job_id):
        p=self._job(job_id)
        if not p.exists(): return None
        try:return json.loads(p.read_text(encoding="utf-8"))
        except Exception:return None
    def save(self, job):
        p=self._job(job["id"]); tmp=p.with_suffix('.tmp'); tmp.write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8'); tmp.replace(p)
    def active(self):
        out=[]
        for p in self.root.glob('*.json'):
            try:j=json.loads(p.read_text(encoding='utf-8'))
            except Exception:continue
            if j.get('status') in {'queued','running'}:out.append(j)
        return out
    def put_artifact(self, job_id, meta, data: bytes):
        d=self.art_root/job_id; d.mkdir(parents=True,exist_ok=True); (d/meta['id']).write_bytes(data)
    def get_artifact(self, job_id, artifact_id):
        p=self.art_root/job_id/artifact_id
        return p.read_bytes() if p.exists() else None


class _PostgresReportStore:
    def __init__(self, database_url: str):
        import psycopg
        self.psycopg=psycopg; self.database_url=database_url; self._init()
    def _connect(self): return self.psycopg.connect(self.database_url, connect_timeout=10)
    def _init(self):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""CREATE TABLE IF NOT EXISTS smartpost_report_jobs (id TEXT PRIMARY KEY,payload JSONB NOT NULL,updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
                cur.execute("""CREATE TABLE IF NOT EXISTS smartpost_report_artifacts (job_id TEXT NOT NULL,artifact_id TEXT NOT NULL,filename TEXT NOT NULL,content_type TEXT NOT NULL,data BYTEA NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),PRIMARY KEY(job_id,artifact_id))""")
            conn.commit()
    def get(self, job_id):
        with self._connect() as conn:
            with conn.cursor() as cur: cur.execute("SELECT payload FROM smartpost_report_jobs WHERE id=%s",(job_id,)); row=cur.fetchone()
        if not row:return None
        return dict(row[0]) if isinstance(row[0],dict) else json.loads(row[0])
    def save(self, job):
        payload=json.dumps(job,ensure_ascii=False)
        with self._connect() as conn:
            with conn.cursor() as cur: cur.execute("""INSERT INTO smartpost_report_jobs(id,payload,updated_at) VALUES(%s,%s::jsonb,NOW()) ON CONFLICT(id) DO UPDATE SET payload=EXCLUDED.payload,updated_at=NOW()""",(job['id'],payload))
            conn.commit()
    def active(self):
        with self._connect() as conn:
            with conn.cursor() as cur: cur.execute("SELECT payload FROM smartpost_report_jobs WHERE payload->>'status' IN ('queued','running')"); rows=cur.fetchall()
        return [dict(r[0]) if isinstance(r[0],dict) else json.loads(r[0]) for r in rows]
    def put_artifact(self, job_id, meta, data: bytes):
        with self._connect() as conn:
            with conn.cursor() as cur: cur.execute("""INSERT INTO smartpost_report_artifacts(job_id,artifact_id,filename,content_type,data) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(job_id,artifact_id) DO UPDATE SET filename=EXCLUDED.filename,content_type=EXCLUDED.content_type,data=EXCLUDED.data""",(job_id,meta['id'],meta['filename'],meta['content_type'],data))
            conn.commit()
    def get_artifact(self, job_id, artifact_id):
        with self._connect() as conn:
            with conn.cursor() as cur: cur.execute("SELECT data FROM smartpost_report_artifacts WHERE job_id=%s AND artifact_id=%s",(job_id,artifact_id)); row=cur.fetchone()
        return bytes(row[0]) if row else None


class ReportJobManager:
    def __init__(self, operation_lock: threading.Lock):
        self.operation_lock=operation_lock; self._queue=queue.Queue(); self._stop=threading.Event(); self._thread=None; self._lock=threading.RLock()
        self._cache = {}
        db=(os.environ.get('DATABASE_URL') or '').strip()
        if db:self._store=_PostgresReportStore(db); self.storage_backend='postgres'
        else:
            cfg=load_config(); self._store=_FileReportStore(resolve_path(cfg,'logs')/'web_report_jobs'); self.storage_backend='files'
        self._recover()
    def start(self):
        if self._thread and self._thread.is_alive():return
        self._stop.clear(); self._thread=threading.Thread(target=self._worker,name='smartpost-web-report-jobs',daemon=True); self._thread.start()
    def stop(self):
        self._stop.set(); self._queue.put(None)
        if self._thread and self._thread.is_alive():self._thread.join(timeout=3)
    def create_job(self,date_text: str):
        selected=datetime.strptime(date_text,'%Y-%m-%d')
        jid=uuid.uuid4().hex
        job={'id':jid,'status':'queued','date':date_text,'created_at':_now(),'started_at':None,'finished_at':None,'progress':{'current':0,'total':4,'message':'En cola…'},'artifacts':[],'no_data':[],'visitas_status':'pending','error':''}
        self._save(job); self._queue.put(jid); return deepcopy(job)
    def retry(self,job_id):
        job=self.get_job(job_id)
        if not job:raise KeyError(job_id)
        return self.create_job(job['date'])
    def get_job(self,job_id):
        with self._lock:
            cached = self._cache.get(job_id)
            if cached and time.monotonic() - cached[0] < 2:
                return deepcopy(cached[1])
            try:
                job = self._store.get(job_id)
                if job:self._remember(job)
                return job
            except Exception:return None
    def get_artifact(self,job_id,artifact_id):
        job=self.get_job(job_id)
        if not job:return None,None
        meta=next((a for a in job.get('artifacts',[]) if a.get('id')==artifact_id),None)
        if not meta:return None,None
        return meta,self._store.get_artifact(job_id,artifact_id)
    def _save(self,job):
        with self._lock:
            self._store.save(job)
            self._remember(job)
    def _remember(self,job):
        self._cache.pop(job['id'],None)
        self._cache[job['id']] = (time.monotonic(),deepcopy(job))
        if len(self._cache)>128:self._cache.pop(next(iter(self._cache)))
    def _progress(self,jid,msg,cur,total=4):
        job=self.get_job(jid)
        if not job:return
        job['progress']={'current':cur,'total':total,'message':msg}; self._save(job)
    def _worker(self):
        while not self._stop.is_set():
            jid=self._queue.get()
            if jid is None:break
            try:self._run(jid)
            finally:self._queue.task_done()
    def _run(self,jid):
        job=self.get_job(jid)
        if not job:return
        job['status']='running'; job['started_at']=_now(); self._save(job)
        try:
            from app.reportes.web_service import generate_reports_and_visits
            selected=datetime.strptime(job['date'],'%Y-%m-%d')
            with self.operation_lock:
                result=generate_reports_and_visits(selected, lambda m,c,t:self._progress(jid,m,c,t))
            metas=[]
            for item in result['artifacts']:
                p=Path(item['path']); aid=uuid.uuid4().hex
                meta={'id':aid,'kind':item['kind'],'seller':item['seller'],'filename':item['filename'],'message':item.get('message',''),'content_type':'application/zip' if p.suffix.lower()=='.zip' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
                self._store.put_artifact(jid,meta,p.read_bytes()); metas.append(meta)
            job=self.get_job(jid) or job; job['status']='completed'; job['finished_at']=_now(); job['progress']={'current':4,'total':4,'message':'Terminado.'}; job['artifacts']=metas; job['no_data']=result.get('no_data',[]); job['visitas_status']=result.get('visitas_status'); self._save(job)
        except Exception:
            job=self.get_job(jid) or job; job['status']='failed'; job['finished_at']=_now(); job['error']=traceback.format_exc(); job['progress']={**job.get('progress',{}),'message':'La generación terminó con un error.'}; self._save(job)
    def _recover(self):
        try:active=self._store.active()
        except Exception:active=[]
        for job in active:
            job['status']='interrupted'; job['finished_at']=_now(); job['error']='El servidor se reinició durante la generación. Podés reintentar.'; job['progress']={**job.get('progress',{}),'message':'Interrumpido por reinicio del servidor.'}; self._save(job)
