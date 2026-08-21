# Secure dashboard configuration

The dashboard now refuses to start unless `DASHBOARD_SECRET_KEY` and `DASHBOARD_PASSWORD` are supplied by the service environment. `PIHOLE_PASSWORD` is optional for live Pi-hole API statistics.

Create a root-readable environment file outside the repository, for example `/etc/dashboard/dashboard.env`, with values generated independently of Git:

```text
DASHBOARD_SECRET_KEY=<random value of at least 32 bytes>
DASHBOARD_PASSWORD=<long unique admin password>
PIHOLE_PASSWORD=<Pi-hole password>
DASHBOARD_COOKIE_SECURE=1
```

Apply permissions with `sudo chown root:root /etc/dashboard/dashboard.env` and `sudo chmod 600 /etc/dashboard/dashboard.env`. Add the following to the real `dashboard.service` unit under `[Service]`:

```ini
EnvironmentFile=/etc/dashboard/dashboard.env
```

Then run `sudo systemctl daemon-reload` and restart the dashboard. Never commit the real environment file or paste its values into the repository. Rotate the previous dashboard, Flask, and Pi-hole credentials because they were present in the old source and should be treated as exposed.

The web terminal is intentionally disabled. Administrative actions now use predefined argument arrays rather than browser-controlled shell strings. The deploy action accepts only the official `sars87/dashboard-v3` HTTPS repository.
