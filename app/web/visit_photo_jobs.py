"""Consultas de fotos en segundo plano, con el bloqueo compartido de Epresis."""
from copy import deepcopy
import asyncio
import logging
import threading
import time
import uuid

from app.core.config import load_config, resolve_path
from app.core.logging import setup_logging
from app.visitas.fotos import today_visits
from app.web.visit_photos import search_visit_photos_web


class VisitPhotoJobs:
    def __init__(self, operation_lock, runner=None):
        self.operation_lock = operation_lock
        self.runner = runner or self._search
        self.jobs = {}
        self.lock = threading.RLock()

    def _search(self, date, progress):
        cfg = load_config()
        logger = setup_logging(resolve_path(cfg, 'logs'), 'visitas_fotos_' + uuid.uuid4().hex, False)
        return asyncio.run(search_visit_photos_web(cfg, logger, date=date, progress=progress))

    def create(self):
        with self.lock:
            # Una consulta activa por servidor; evita duplicados al tocar varias veces.
            for job in self.jobs.values():
                if job['status'] in ('queued', 'running'):
                    return deepcopy(job)
            cutoff = time.time() - 86400
            self.jobs = {k: v for k, v in self.jobs.items() if v['created_at'] >= cutoff}
            # No retener veinte listados completos en una instancia de 512 MB.
            while len(self.jobs) >= 2:
                self.jobs.pop(next(iter(self.jobs)))
            job = dict(id=uuid.uuid4().hex, status='queued', date=today_visits(), created_at=time.time(), message='Esperando turno…', rows=[])
            self.jobs[job['id']] = job
            snapshot = deepcopy(job)
            threading.Thread(target=self._run, args=(job['id'],), daemon=True).start()
            return snapshot

    def get(self, job_id):
        with self.lock:
            return deepcopy(self.jobs.get(job_id))

    def _update(self, job_id, **values):
        with self.lock:
            self.jobs[job_id].update(values)

    def _run(self, job_id):
        try:
            with self.operation_lock:
                self._update(job_id, status='running', message='Buscando visitas de hoy…')
                result = self.runner(self.get(job_id)['date'], lambda message: self._update(job_id, message=message))
                self._update(job_id, **result, status='completed', message='Consulta terminada.')
        except Exception:
            logging.getLogger(__name__).exception('Error consultando fotos de visitas')
            self._update(job_id, status='failed', message='No se pudo completar la consulta. Volvé a consultar.')
