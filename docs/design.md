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
| `static/js/map_export.js` | SVG export and print sheet of the map |
| `static/js/prefix_tree.js` | Prefix tree in the map page sidebar |
| `static/js/topbar.js` | Top bar: freshness indicator, search box |

## Update run

1. Fetch all objects from NetBox: prefixes, IP addresses, VRFs, tenants; optionally prefix roles, IP ranges, VLANs, sites, locations, regions and site groups (names only; skipped with a warning when the token cannot read them). Records are flattened with pynetbox `serialize()`: nested objects become ids, choice fields become their value (`"active"`, `"reserved"`).
2. Build one prefix tree per VRF.
3. For every IPv4 prefix write `data-<vrf>-<prefix>.json` and `address_map-<vrf>-<prefix>.png`: an address map for /16 and longer, a layered map for shorter prefixes.
4. Write `vrf.json`, `names.json` (tenant and role names), `prefix_tree.json` (prefix list per VRF), `search_index.json` (IPv4 addresses with a DNS name or description) and `summary.json` (per VRF: IPv4 prefix and address counts, top-level prefixes with usage). Until the first update writes `summary.json`, the VRF pages derive the top-level prefixes from `prefix_tree.json` without usage.

`<vrf>` is the VRF id or `None`; in `<prefix>`, `.` and `/` are replaced with `_`. All files are written to a temporary name and renamed, so readers never see partial files.

Each data file keeps `changes`: what the last update that changed the prefix added, removed or changed, compared with the previous data file: IP records (address and VRF; status, role, DNS name) and nested prefixes, at most 1,000 of each with full counts, and the time (`at`, `since`). An update without changes keeps the previous record; the first update has none.

An image is redrawn only when its inputs change. The inputs are hashed (`render_hash` in the data file): address, status and role of each IP, nested prefixes with their tenant colors and statuses, cell size and `RENDER_VERSION`. Bump `RENDER_VERSION` when drawing code changes.

## Address membership

Following NetBox `Prefix.get_child_ips()`, a prefix contains the IP addresses of its own VRF. A Global container contains addresses and prefixes of all VRFs; when one address exists in several VRFs, the record with a role wins, then an active one, then reserved, then inactive.

## Layout

A prefix with `h` host bits is drawn on a grid of `2^ceil(h/2)` × `2^floor(h/2)` cells. The address offset within the prefix is decoded to `(x, y)` by de-interleaving its bits (Morton order). Any aligned subnet then occupies a rectangle. When `h` is odd the grid is two squares side by side; the second half of the address range is in the right square.

Each cell is `CELL_SIZE` pixels: a 1 px gap followed by the cell body. The axes map one data unit to one output pixel, so cell edges fall on whole pixels across the image.

## Rendering

| Element | Style |
|---|---|
| Nested prefix | Tenant color blended 50% with white, dotted border; longer prefixes on top |
| Reserved or deprecated prefix | Diagonal stripes, 1 px every two cells, at half the brightness of what is under them; a child prefix with a tenant covers them, one without does not |
| IP with a role | Red |
| DHCP or SLAAC IP | Black at 55% opacity |
| Reserved or deprecated IP | Black at 25% opacity |
| Inactive IP | Black at 10% opacity |
| Address in an IP range, without an IP record | Dark gray dot in the middle of the cell |
| Other IP | Black |
| Grid | Dotted lines every 16 cells, inner lines only |

Prefix outlines and the grid are drawn with matplotlib; IP cells are painted into the pixel array afterwards (one matplotlib patch per IP made large maps slow: 50,000 IPs took 112 s, now 34 s).
| Labels | Third octet of each /24 in a 3×5 pixel font, gray, on a free spot near the block center; none when the block has no room |

### Layered maps

Prefixes shorter than /16 would need a grid of 4096 × 4096 cells or more. They are drawn with one cell per aligned block of length `min(prefix length + 16, 24)` (a /8 gets /24 blocks), in the same Morton layout and with the same cell size. The image is written pixel by pixel (numpy), not through matplotlib patches.

| Element | Style |
|---|---|
| Block covered by a nested prefix | Fill color of the longest such prefix |
| Block with nested prefixes inside | Checkerboard of the shortest such prefix with a tenant, gray when none has one |
| IP addresses in the block | Black overlay, 25% opacity for one address up to 90% for a full block |
| Direct child prefix of a block or larger | Dark outline on the cell gap lines |
| Reserved or deprecated prefix of a block or larger | Stripes as on address maps |
| Grid | Light lines every 16 cells |
| Labels | As on address maps, for each 16 × 16-cell group (the second octet of a /16 on a /8 map); none when no single octet tells the groups apart (/1 to /7) |

The data file carries `layer` (`block_len`, `blocks`: block index and IP count) instead of the IP list. On the page a cell is a block: the inspector shows its IP count, the prefix chain, prefixes inside it and free blocks down to the block size; double-click opens the map of the child prefix covering the block, or of the first prefix inside it.

Tenant colors are taken from a 16-color palette by tenant id, so a tenant keeps its color when others are added or removed. The palette has no gray: a gray fill would read as a reserved IP. Tenant ids 16 apart share a color; the map page legend marks tenants of the current map that share one (`=`, with the other names in the tooltip), and the exported SVG names them after the tenant.

## Updates

`UpdaterManager` runs updates in one worker thread:

- An update request when idle starts a run immediately.
- Requests during a run or within `UPDATE_DEBOUNCE_SECONDS` of the last start are merged into one follow-up run, started no earlier than that interval after the previous start.
- Exceptions are recorded and do not stop the thread.

The web app requests an update at startup (unless `INITIAL_UPDATE=0`) and on each relevant webhook. The webhook accepts `created`, `updated` and `deleted` events for prefixes, IP addresses, IP ranges, VRFs and tenants. With `WEBHOOK_SECRET` set, the `X-Hook-Signature` header must be the HMAC-SHA512 of the request body.

Because the updater lives in the web process, the server runs with a single gunicorn worker.

## Map page

Layout: top bar (VRF, prefix path, search, freshness), prefix tree on the left, map in the center, inspector on the right, legend and usage at the bottom. The side panels collapse (`[`, `]`); the state is kept in local storage. The page configuration (prefix, parents, names, URLs) is embedded as JSON; the browser loads the PNG and the prefix data file (`/data/<vrf>/<prefix>`, gzip-compressed when accepted). The data file carries the grid size, cell size, nested prefixes with their fill colors, IP addresses and parent prefixes, so the page resolves the cell under the pointer with the same layout as the renderer. Missing fields (data files from older versions) are derived or treated as empty.

- Zoom is in whole device pixels per cell (4, 5, 6, 7, 8, 10, 12, ... with the default cell size); Fit picks the largest one that fits the view. The PNG is scaled with nearest-neighbour sampling; since a cell spans exactly cs image pixels and c device pixels, every cell gets the same pixel pattern. Below 1x the cell size halves down to 1 device pixel (2 and 1 with the default cell size), so a /8 layered map fits small screens; there the gaps cannot be kept and the PNG is scaled smoothly. Overlays are placed on cell edges.
- Ctrl (Cmd) + wheel and touchpad pinch zoom one step per notch, keeping the map point under the pointer in place once the map overflows the view; the plain wheel scrolls. Dragging with the mouse pans; a move of 4 px or more is a drag, and the click that ends it does not pin.
- The pinned address (or outlined prefix) is written to `?focus=` with `history.replaceState`, so the URL is a permalink. Arrow keys move the pin by one cell (Shift: 16), Enter opens it, `c` copies the address. Copy buttons sit next to addresses, prefixes and free blocks; on plain-http hosts, where `navigator.clipboard` is unavailable, a hidden textarea and `execCommand('copy')` are used.
- The free-block list has a size picker: "largest" lists the largest free blocks; `/N` lists the first free aligned /N blocks by address, as NetBox "first available prefix" would. The choice is kept in local storage.
- Hovering shows the address, its IP record or "free", the prefix chain and the free blocks of the innermost prefix in the inspector; the cell and the prefix are outlined. Clicking pins the cell; clicking it again or Esc unpins.
- Double-clicking opens the child prefix that contains the cell, otherwise the IP address in NetBox.
- Usage of every prefix, containers included, is the share of its addresses with an IP record, counted through any nested prefixes.
- NetBox IP ranges overlapping a prefix (of its VRF; of all VRFs for a Global container) are stored in its data file (`ip_ranges`). The inspector shows the ranges of an address or block. Ranges take space like child prefixes: their addresses are never free. Without `ipam.view_iprange` on the token, ranges are skipped with a warning.
- Addresses with several IP records (several VRFs under a Global container, or NetBox duplicates) get a "N records" pill and the list of records in the inspector; the prefix summary lists them.
- Free blocks are the largest aligned blocks with no IP record and no child prefix. Child containers are transparent: what is not assigned inside them is free. As in NetBox, the network and broadcast addresses of a prefix are not free unless it is a container, a pool, a /31 or a /32; the inspector labels them. Data files of prefixes without an image carry no IP list, so their free blocks are not shown.
- The prefix tree shows the path from the outermost parent to the current prefix; other branches load on expand from `/data/...?nav=1`, which omits addresses and nested prefixes. Tree rows and the map highlight each other.
- Text search: other queries of 2 characters or more go to `/search` as text, matched case-insensitively against IP DNS names and descriptions (`search_index.json`) and prefix descriptions, tenant and role names; IP results link to the innermost prefix map with `?focus=`. At most 50 results.
- Search: an address or prefix inside the map is pinned or outlined in place; other queries go to `/search`, which returns, per VRF, the prefix itself or the innermost prefix containing the query, with the IP record if any. Result links carry `?focus=<query>`, which pins or outlines it when the map opens.
- Export and print (`static/js/map_export.js`): an SVG is drawn in the browser from the data file, with the same layout as the PNG: one rect per IP (per block with its usage darkness on layered maps), nested prefixes with tenant fills and dotted outlines, the octet labels as text, a title and a legend. "Download SVG" saves it; on print (`beforeprint`, Ctrl+P included) it replaces the page through the print stylesheet, so the browser prints a vector map with legend and no UI, landscape for 2:1 maps. In black and white, tenants get hatches instead of colors (16 hatches in order of first appearance on the map; beyond 16 the legend names tenants sharing one) and IPs with a role become hollow black cells. Hatches and the checkerboard of layered maps are drawn as vector lines, dots and squares clipped to each rectangle, not as SVG patterns: Chromium prints patterns as bitmaps (the /17 of the test data gave a 29 MB PDF of raster tiles, a /16 2.6 MB with 270 of them; now 0.3 and 0.4 MB, all vector). The hatch pitch is about 1.6 mm on paper, not tied to the cell size, so it does not read as the cell grid; a rectangle too small for it gets a finer pitch.
- Clicking a tenant in the legend (or Enter on it) outlines its outermost prefixes on the map and names them in a toast; clicking it again clears the outline.
- The freshness dot polls `/healthz` and turns amber when the last update failed, the updater stopped or the data is older than 24 h.
- Colors of the page follow the system light or dark theme; the map keeps its white background.

## Observability

- `/healthz` returns 200 while the updater thread is alive, with the time of the last successful update and the last error.
- `/metrics` exposes update counts, failures, duration, last success time and webhook counts by result.
- `/errors` shows the last 500 warnings and errors of the process.
- The container healthcheck (`app/healthcheck.py`) calls `/healthz` on 127.0.0.1 and ignores proxy environment variables.
