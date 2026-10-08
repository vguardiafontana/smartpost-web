# SmartPost Web — instalación en Ubuntu

La API escucha únicamente en `127.0.0.1:8787`. Tailscale Serve la publica por HTTPS sólo dentro del tailnet.

## Requisitos
- Ubuntu 24.04 LTS.
- ZIP completo de SmartPost v2.7.0 en `/tmp/smartpost.zip`.
- Cuenta Tailscale.

## Instalación base

```bash
sudo apt update
sudo apt install -y unzip python3 python3-venv python3-pip curl openssl
sudo useradd --system --create-home --shell /usr/sbin/nologin smartpost || true
sudo mkdir -p /opt/smartpost /var/lib/smartpost /opt/smartpost-playwright
sudo unzip -o /tmp/smartpost.zip -d /opt/smartpost
sudo python3 -m venv /opt/smartpost/.venv
sudo /opt/smartpost/.venv/bin/pip install -U pip
sudo /opt/smartpost/.venv/bin/pip install -r /opt/smartpost/requirements-web.txt
sudo env PLAYWRIGHT_BROWSERS_PATH=/opt/smartpost-playwright /opt/smartpost/.venv/bin/playwright install --with-deps chromium
sudo chown -R smartpost:smartpost /opt/smartpost /var/lib/smartpost /opt/smartpost-playwright
```

## Secretos

Generar secreto de sesión:

```bash
openssl rand -hex 32
```

Crear `/etc/smartpost-web.env`:

```text
SMARTPOST_EPRESIS_USER="TU_USUARIO"
SMARTPOST_EPRESIS_PASSWORD="TU_PASSWORD"
SMARTPOST_WEB_PIN="TU_PIN"
SMARTPOST_WEB_SESSION_SECRET="PEGA_EL_SECRETO_GENERADO"
SMARTPOST_DATA_DIR="/var/lib/smartpost"
PLAYWRIGHT_BROWSERS_PATH="/opt/smartpost-playwright"
SMARTPOST_WEB_HOST="127.0.0.1"
SMARTPOST_WEB_PORT="8787"
```

Luego:

```bash
sudo chmod 600 /etc/smartpost-web.env
sudo cp /opt/smartpost/deploy/smartpost-web.service /etc/systemd/system/smartpost-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now smartpost-web
sudo systemctl status smartpost-web --no-pager
```

## Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale serve --bg http://127.0.0.1:8787
sudo tailscale serve status
```

Abrir en el iPhone la URL HTTPS que muestra `tailscale serve status`.

## Logs

```bash
sudo journalctl -u smartpost-web -f
sudo ls -lah /var/lib/smartpost/runtime/logs
```

Los trabajos web se guardan también como JSON en `runtime/logs/web_jobs`.
