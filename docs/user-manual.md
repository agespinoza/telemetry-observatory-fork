# User manual

Telemetry Observatory presents resource and process information from one macOS host. The host sensor runs natively on macOS; the API, poller, MongoDB, and dashboard run in Docker containers.

## Start and open the dashboard

Complete the setup in the [README](../README.md), including creating `.env`, installing the host sensor, and starting Docker Compose. Open <http://127.0.0.1:8080>.

Check whether the services are running with:

```sh
docker compose ps
```

## Read the dashboard

- **CPU utilization** shows current CPU use.
- **Memory used** shows used physical memory and its percentage of total physical memory.
- **Disk read** and **Disk write** show rates calculated from the difference between the two newest cumulative I/O samples. Rates are shown as unavailable until two samples exist.
- **Resource history** plots CPU and memory percentages from recent samples.
- **Storage** lists mounted volumes and their used capacity.
- **Applications by memory** lists up to twelve processes, ordered by resident memory use.
- The dashboard requests updated data every five seconds.

The header status describes the latest sample/API connection:

- **Live telemetry** means the latest sample is within the freshness window.
- **Stale sample** means the API is reachable, but the latest sample is older than the freshness window. The sensor or poller may not be delivering new samples.
- **Disconnected** means the dashboard could not retrieve samples from the API.

Some process or volume information may be absent because macOS denied access. A process CPU reading can be zero on its first observation.

## Change polling and retention

Use the **Data policy** form to update:

- **Poll every**: 2 to 3600 seconds. The default is 10 seconds.
- **Retain for**: 1 to 365 days. The default is 7 days.

Enter the `ADMIN_TOKEN` value from `.env` in the administrator token field and choose **Save policy**. The API rejects invalid or missing tokens. The browser does not persist the token and clears it after a successful save.

The poller reads the updated frequency at the start of its next cycle, after its current wait. When retention changes, the API recalculates expiry times for existing samples. MongoDB's TTL monitor removes expired records asynchronously, so deletion may not happen immediately.

## Stop, restart, and remove data

Restart application containers:

```sh
docker compose restart api poller dashboard
```

Stop containers while preserving saved samples:

```sh
docker compose down
```

Stop containers and permanently delete the MongoDB volume and saved samples:

```sh
docker compose down -v
```

Stop the macOS host sensor separately:

```sh
launchctl bootout "gui/$(id -u)/com.telemetry-observatory.sensor"
```

Run `./scripts/install-sensor.sh` again to install/start the sensor, including after changing `.env` or moving the project directory. Back up the `mongo_data` Compose volume before removing it if the samples need to be retained.

## Troubleshooting

1. **Dashboard does not open:** Check `docker compose ps` and confirm Docker Desktop is running. The dashboard port can be changed with `DASHBOARD_PORT` in `.env`; the default is 8080.
2. **Disconnected status:** Inspect API and dashboard logs with `docker compose logs --tail=100 api dashboard`. The dashboard is served through Nginx, which proxies `/api/` requests to the API.
3. **Stale sample:** Check that the host sensor is installed and running, and inspect `audits/sensor.jsonl` and `audits/poller.jsonl`. Verify that `SENSOR_TOKEN` in `.env` is valid and that the sensor port is reachable from Docker Desktop.
4. **Services fail to start:** Check API and MongoDB startup output with `docker compose logs --tail=100 api mongo`. Verify `ADMIN_TOKEN` and `SENSOR_TOKEN` are each set to at least 24 characters in `.env`.
5. **Policy save fails:** Confirm the administrator token matches `ADMIN_TOKEN` in `.env`; check `audits/api.jsonl` for denied authorization or validation requests.

Audit files are written under `audits/`: `sensor.jsonl`, `poller.jsonl`, `api.jsonl`, `dashboard-access.log`, `dashboard-error.log`, and `mongo.log`. These logs can contain operational and request metadata; protect and rotate them appropriately.
