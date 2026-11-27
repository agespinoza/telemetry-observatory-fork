# Design document

## Purpose and scope

Telemetry Observatory collects resource samples from one macOS host, stores them in MongoDB, and displays recent data in a local web dashboard. The native sensor is required because Docker Desktop containers run in a Linux VM and cannot report the macOS host's counters directly. This is a single-host observability tool, not a remote fleet or alerting system.

## Architecture

```text
[macOS sensor] -- GET /sample --> [Poller] -- POST sample --> [API] <--> [MongoDB]
                                                               ^
[Browser] -- localhost:8080 --> [Nginx dashboard] -- /api proxy-+
```

The sensor is a host process managed by `launchd`. The other four services are defined in `compose.yaml` and communicate over a private Compose network. Only the dashboard port is published to the host, bound to loopback by default (`127.0.0.1:8080`). Nginx serves the static page and proxies `/api/` requests to the API.

## Components and responsibilities

| Component | Responsibility |
| --- | --- |
| `host_sensor.py` | Reads host metrics using `psutil`; serves a token-protected `GET /sample` response. |
| `poller/main.py` | Reads current policy, fetches a sensor sample, and submits it to the API on the configured schedule. |
| `api/main.py` | Validates and stores samples, returns recent samples/settings, authorizes writes, and manages retention expiry. |
| MongoDB | Stores time-stamped samples and policy settings; expires samples using a TTL index. |
| `web/` | Static dashboard UI; fetches API data and submits policy updates. |
| Nginx | Serves the UI and proxies API paths within the Compose network. |

## Data flow

1. The sensor collects CPU use, virtual and swap memory, mounted volumes and disk usage, cumulative disk I/O, network counters, and process data. It skips processes or mounts that macOS does not permit it to read. It limits its returned process list to thirty entries; the UI displays the twelve largest by memory.
2. The poller reads `GET /api/settings` to get its interval, requests `GET /sample` with `X-Sensor-Token`, then posts the resulting JSON to `POST /api/samples` using `Authorization: Bearer <ADMIN_TOKEN>`.
3. The API validates the sample shape and timestamp (within five minutes of the API clock), records it with an `expires_at` calculated from the current retention setting, and stores it in MongoDB.
4. The dashboard fetches recent samples and settings through Nginx. The page refreshes sample data every five seconds. Disk rates are computed in the browser from the difference between the newest two cumulative disk I/O records.
5. The API creates a MongoDB TTL index on `expires_at`. Changing retention recalculates existing records' expiry values; TTL cleanup itself is asynchronous.

The sample payload includes host name, sample time, CPU, memory, swap, disks, disk I/O, network I/O, and applications. MongoDB stores samples in `observatory.samples` and the global polling/retention policy in `observatory.settings`.

## HTTP interfaces

### Host sensor

| Method and path | Authentication | Purpose |
| --- | --- | --- |
| `GET /sample` | `X-Sensor-Token` header | Return one host sample. Other paths return 404; an invalid or too-short configured token is rejected. |

The sensor binds to `0.0.0.0` by default so Docker Desktop can reach the host service. It is not published by Compose; host firewall rules should be considered on untrusted networks.

### API

| Method and path | Authentication | Purpose |
| --- | --- | --- |
| `GET /api/health` | None | Ping MongoDB and report API health. |
| `GET /api/settings` | None | Return current policy, defaulting to 10 seconds and 7 days before a policy is saved. |
| `PUT /api/settings` | `Authorization: Bearer <ADMIN_TOKEN>` | Validate and save the 2–3600 second polling interval and 1–365 day retention period. |
| `POST /api/samples` | `Authorization: Bearer <ADMIN_TOKEN>` | Validate, timestamp, and store a sample. |
| `GET /api/samples?limit=N` | None | Return newest samples, default 120, with allowed limits from 1 to 1000. |

The API's interactive OpenAPI/Redoc documentation endpoints are disabled. The API has no published host port in the Compose configuration; the dashboard reaches it through Nginx.

## Configuration and dependencies

Compose reads `ADMIN_TOKEN`, `SENSOR_TOKEN`, `SENSOR_PORT`, and `DASHBOARD_PORT` from `.env`. The two tokens must be different and at least 24 characters long. `MONGO_URI`, `API_URL`, `SENSOR_URL`, and audit paths are set for container-to-container or host-to-container communication in `compose.yaml`.

Python package pins and acquisition instructions are listed in the [README](../README.md). Compose builds the Python API and poller images and pulls MongoDB and Nginx images. The host sensor and tests use the local Python virtual environment.

## Persistence, logging, and operations

- `mongo_data` is a named Docker volume that survives `docker compose down`. `docker compose down -v` removes it.
- The project `audits/` directory is mounted into the containers. Services append JSONL or Nginx/MongoDB log output there.
- `scripts/install-sensor.sh` generates `.sensor.launchd.plist` from the current project path and `.env`, then bootstraps the service. Re-run it after changing the path or sensor configuration.
- The local dashboard is not configured for remote exposure, TLS termination, or multi-user access.

## Security boundaries and limitations

- Store `.env`, the generated launchd plist, audit logs, and database backups as private files; tokens grant access to data ingestion or policy changes.
- The dashboard is loopback-bound by default. The native sensor listens on all host interfaces unless `SENSOR_BIND` is overridden, and protects sample access with `SENSOR_TOKEN`.
- The API read endpoints are unauthenticated, but are available to the dashboard through the local Nginx proxy and are not directly published as host ports by Compose.
- Collection is limited by permissions macOS grants to the sensor. Process CPU can be zero on an initial observation.
- TTL expiration is asynchronous, sample charts show recent stored data, and there is no remote-host aggregation, alerting, or backup automation.
