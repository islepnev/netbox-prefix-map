# NetBox Prefix Map

Renders IPv4 prefixes from [NetBox](https://github.com/netbox-community/netbox) as pixel grids: one cell per address, laid out along a Z-order curve so that every aligned subnet is a rectangle. Child prefixes are shaded by tenant, used addresses are drawn on top. Maps are regenerated when NetBox reports changes through a webhook.

The web interface is served under a base path (default `/prefix-map`) so it can share a host and reverse proxy with NetBox.

## Requirements

- NetBox 4.x and an API token with read access to IPAM (prefixes, IP addresses, VRFs; roles optional) and Tenancy (tenants)
- Docker with Compose, or Python 3.13

## Configuration

Settings are read from the environment or from a `.env` file in the project directory.

| Variable | Default | Description |
|---|---|---|
| `NETBOX_API_URL` | | NetBox base URL, e.g. `https://netbox.example.com` |
| `NETBOX_API_TOKEN` | | API token |
| `NETBOX_TIMEOUT` | `30` | API request timeout, seconds |
| `BASE_PATH` | `/prefix-map` | URL path prefix of the web interface |
| `OUTPUT_DIR` | `output` | Generated files; relative paths are resolved against the project directory |
| `CELL_SIZE` | `4` | Cell size in pixels |
| `WEBHOOK_SECRET` | | Shared secret of the NetBox webhook; when set, unsigned requests are rejected |
| `UPDATE_DEBOUNCE_SECONDS` | `60` | Minimum interval between webhook-triggered updates |
| `INITIAL_UPDATE` | `1` | Set to `0` to skip the update at startup |
| `PORT` | `5000` | Listening port |

## Running

With Docker:

```bash
make up
```

The container serves requests immediately and updates the maps in the background. Generated files are kept in the `output` volume. `make logs` and `make down` show the logs and stop the container.

Without Docker:

```bash
pip install -r requirements.txt
python -m app.cli       # one-off update
python -m app.webapp    # development server
```

## NetBox setup

### Webhook

1. Operations › Integrations › Webhooks › Add: URL `http://<host>:5000/prefix-map/webhook`, method `POST`, content type `application/json`, secret as in `WEBHOOK_SECRET`.
2. Operations › Integrations › Event Rules › Add: object types IPAM › Prefix, IPAM › IP Address, IPAM › VRF, Tenancy › Tenant; events created, updated, deleted; action: the webhook above.

Events for other object types are ignored. A burst of events triggers one update immediately and at most one follow-up after `UPDATE_DEBOUNCE_SECONDS`.

### Map button on prefix pages

Customization › Custom Links › Add, object type IPAM › Prefix:

- Link text: `Map`
- Link URL:

  ```
  /prefix-map/map/{{ object.vrf.pk if object.vrf else 'None' }}/{{ (object.prefix | string).replace('.', '_').replace('/', '_') }}
  ```

## Reverse proxy

Apache, in the NetBox virtual host:

```apache
<Location /prefix-map>
    ProxyPass http://localhost:5000/prefix-map
    ProxyPassReverse http://localhost:5000/prefix-map
</Location>
```

Requires `mod_proxy` and `mod_proxy_http`.

## Endpoints

All paths are relative to `BASE_PATH`.

| Path | Description |
|---|---|
| `/` | VRF list with prefix and address counts |
| `/map/<vrf>` | Top-level prefixes of a VRF with usage |
| `/map/<vrf>/<prefix>` | Map page; `<vrf>` is the VRF id or `None` for Global, `<prefix>` uses `_` for `.` and `/` |
| `/search?q=<address or prefix>` | Maps showing an IPv4 address or prefix, across VRFs (JSON) |
| `/webhook` | NetBox webhook receiver |
| `/healthz` | Liveness and data age (JSON); used by the container healthcheck |
| `/metrics` | Prometheus metrics |
| `/errors` | Recent warnings and errors |

## Limitations

- IPv4 only; IPv6 prefixes are skipped.
- Prefixes of /16 and longer get one cell per address. Shorter prefixes get a layered map with one cell per aligned block (/24 for a /8, at most 65,536 cells), shaded by the number of IP addresses in it.
- The updater runs inside the web process; run a single web worker.
- No authentication; restrict access at the reverse proxy if needed.

## Development

```bash
make test
```

Tests run offline against a synthetic dataset (`tests/synthetic_data.py`). Design notes: [docs/design.md](docs/design.md).
