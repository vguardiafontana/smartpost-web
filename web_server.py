from __future__ import annotations

import os
import uvicorn


if __name__ == "__main__":
    # Render inyecta PORT y exige escuchar en 0.0.0.0. En Windows/local se
    # conserva SMARTPOST_WEB_HOST/PORT y los valores históricos.
    port = int(os.environ.get("PORT") or os.environ.get("SMARTPOST_WEB_PORT") or "8787")
    host = os.environ.get("SMARTPOST_WEB_HOST") or ("0.0.0.0" if os.environ.get("RENDER") else "127.0.0.1")
    uvicorn.run(
        "app.web.server:app",
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
