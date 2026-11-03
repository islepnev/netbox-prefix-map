# Design

## Components

| Module | Role |
|---|---|
| `app/netbox_integration.py` | Fetches prefixes, IP addresses, VRFs, tenants and prefix roles through pynetbox |
| `app/prefix_tree.py` | Per-VRF prefix trees (pytricia) |
| `app/cli.py` | Update run: fetch, build trees, write data files and images |
| `app/plot_map.py` | Image rendering (matplotlib, Agg backend) |
| `app/updater_manager.py` | Background update scheduling |
| `app/webapp.py` | Flask application: pages, data endpoint, webhook, health and metrics |
| `static/js/map.js` | Map page: zoom, overlays, inspector, legend, search within the map |
| `static/js/prefix_tree.js` | Prefix tree in the map page sidebar |
| `static/js/topbar.js` | Top bar: freshness indicator, search box |

## Update run

1. Fetch all objects from NetBox. Records are flattened with pynetbox `serialize()`: nested objects become ids, choice fields become their value (`"active"`, `"reserved"`).
2. Build one prefix tree per VRF.
3. For every IPv4 prefix write `data-<vrf>-<prefix>.json` and, for /16 and longer, `address_map-<vrf>-<prefix>.png`.
4. Write `vrf.json`, `names.json` (tenant and role names), `prefix_tree.json` (prefix list per VRF) and `summary.json` (per VRF: IPv4 prefix and address counts, top-level prefixes with usage). Until the first update writes `summary.json`, the VRF pages derive the top-level prefixes from `prefix_tree.json` without usage.

`<vrf>` is the VRF id or `None`; in `<prefix>`, `.` and `/` are replaced with `_`. All files are written to a temporary name and renamed, so readers never see partial files.

An image is redrawn only when its inputs change. The inputs are hashed (`render_hash` in the data file): address, status and role of each IP, nested prefixes with their tenant colors, cell size and `RENDER_VERSION`. Bump `RENDER_VERSION` when drawing code changes.

## Address membership

Following NetBox `Prefix.get_child_ips()`, a prefix contains the IP addresses of its own VRF. A Global container contains addresses and prefixes of all VRFs; when one address exists in several VRFs, the record with a role wins, then an active one, then reserved, then inactive.

## Layout

A prefix with `h` host bits is drawn on a grid of `2^ceil(h/2)` × `2^floor(h/2)` cells. The address offset within the prefix is decoded to `(x, y)` by de-interleaving its bits (Morton order). Any aligned subnet then occupies a rectangle. When `h` is odd the grid is two squares side by side; the second half of the address range is in the right square.

Each cell is `CELL_SIZE` pixels: a 1 px gap followed by the cell body. The axes map one data unit to one output pixel, so cell edges fall on whole pixels across the image.

## Rendering

| Element | Style |
|---|---|
| Nested prefix | Tenant color blended 50% with white, dotted border; longer prefixes on top |
| IP with a role | Red |
| Reserved IP | Black at 25% opacity |
| Inactive IP | Not drawn |
| Other IP | Black |
| Grid | Dotted lines every 16 cells, /24 labels |

Tenant colors are taken from a 16-color palette by tenant id, so a tenant keeps its color when others are added or removed.

## Updates

`UpdaterManager` runs updates in one worker thread:

- An update request when idle starts a run immediately.
- Requests during a run or within `UPDATE_DEBOUNCE_SECONDS` of the last start are merged into one follow-up run, started no earlier than that interval after the previous start.
- Exceptions are recorded and do not stop the thread.

The web app requests an update at startup (unless `INITIAL_UPDATE=0`) and on each relevant webhook. The webhook accepts `created`, `updated` and `deleted` events for prefixes, IP addresses, IP ranges, VRFs and tenants. With `WEBHOOK_SECRET` set, the `X-Hook-Signature` header must be the HMAC-SHA512 of the request body.

Because the updater lives in the web process, the server runs with a single gunicorn worker.

## Map page

Layout: top bar (VRF, prefix path, search, freshness), prefix tree on the left, map in the center, inspector on the right, legend and usage at the bottom. The side panels collapse (`[`, `]`); the state is kept in local storage. The page configuration (prefix, parents, names, URLs) is embedded as JSON; the browser loads the PNG and the prefix data file (`/data/<vrf>/<prefix>`, gzip-compressed when accepted). The data file carries the grid size, cell size, nested prefixes with their fill colors, IP addresses and parent prefixes, so the page resolves the cell under the pointer with the same layout as the renderer. Missing fields (data files from older versions) are derived or treated as empty.

- Zoom steps are whole device pixels per image pixel; the image is never resampled. Fit picks the largest such step that fits the view. Overlays are placed on cell edges.
- Hovering shows the address, its IP record or "free", the prefix chain and the free blocks of the innermost prefix in the inspector; the cell and the prefix are outlined. Clicking pins the cell; clicking it again or Esc unpins.
- Double-clicking opens the child prefix that contains the cell, otherwise the IP address in NetBox.
- Free blocks are the largest aligned blocks with no IP record and no child prefix. Data files of prefixes without an image carry no IP list, so their free blocks are not shown.
- The prefix tree shows the path from the outermost parent to the current prefix; other branches load on expand from `/data/...?nav=1`, which omits addresses and nested prefixes. Tree rows and the map highlight each other.
- Search: an address or prefix inside the map is pinned or outlined in place; other queries go to `/search`, which returns, per VRF, the prefix itself or the innermost prefix containing the query, with the IP record if any. Result links carry `?focus=<query>`, which pins or outlines it when the map opens.
- The freshness dot polls `/healthz` and turns amber when the last update failed, the updater stopped or the data is older than 24 h.
- Colors of the page follow the system light or dark theme; the map keeps its white background.

## Observability

- `/healthz` returns 200 while the updater thread is alive, with the time of the last successful update and the last error.
- `/metrics` exposes update counts, failures, duration, last success time and webhook counts by result.
- `/errors` shows the last 500 warnings and errors of the process.
- The container healthcheck (`app/healthcheck.py`) calls `/healthz` on 127.0.0.1 and ignores proxy environment variables.
