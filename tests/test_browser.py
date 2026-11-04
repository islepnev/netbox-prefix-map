import ipaddress
import json
import os
import socket
import threading

import pytest

from app.plot_map import decode_offset, get_max_bits
from tests.conftest import CELL_SIZE

playwright_api = pytest.importorskip("playwright.sync_api")

BASE = '/prefix-map'
NETBOX = 'https://netbox.example.test'


@pytest.fixture(scope="module")
def server(output_dir):
    from werkzeug.serving import make_server

    import app.webapp as webapp
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    srv = make_server('127.0.0.1', port, webapp.app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{port}'
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        executable = os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None
        b = p.chromium.launch(executable_path=executable)
        yield b
        b.close()


@pytest.fixture
def open_page(browser, server):
    contexts = []

    def _open(path, device_scale_factor=1, viewport=(1400, 900), route=None):
        ctx = browser.new_context(viewport={'width': viewport[0], 'height': viewport[1]},
                                  device_scale_factor=device_scale_factor)
        contexts.append(ctx)
        page = ctx.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and 'Failed to load resource' not in m.text
                and page.errors.append(m.text))
        page.on('response', lambda r: r.status >= 400 and page.errors.append(f'{r.status} {r.url}'))
        if route:
            page.route(*route)
        page.goto(server + path)
        return page

    yield _open
    for ctx in contexts:
        ctx.close()


def wait_for_map(page):
    page.wait_for_function("document.body.dataset.ready === '1'")


def cell_center(page, x, y):
    """Viewport coordinates of a cell center, scrolling the map so that the cell is visible."""
    box = page.evaluate('''([x, y, cs]) => {
        const img = document.getElementById("map-img"), vp = document.getElementById("viewport");
        let r = img.getBoundingClientRect();
        const k = r.width / img.naturalWidth, v = vp.getBoundingClientRect();
        const cx = r.left + (x * cs + cs / 2) * k, cy = r.top + (y * cs + cs / 2) * k;
        if (cx < v.left + 8 || cx > v.right - 60 || cy < v.top + 8 || cy > v.bottom - 60) {
            vp.scrollLeft += cx - (v.left + v.width / 2);
            vp.scrollTop += cy - (v.top + v.height / 2);
            r = img.getBoundingClientRect();
        }
        return {left: r.left, top: r.top, k};
    }''', [x, y, CELL_SIZE])
    cs = CELL_SIZE
    return box['left'] + (x * cs + cs / 2) * box['k'], box['top'] + (y * cs + cs / 2) * box['k']


def cell_of(prefix, address):
    net = ipaddress.ip_network(prefix)
    host_bits = 32 - net.prefixlen
    width, height = 2 ** (host_bits - host_bits // 2), 2 ** (host_bits // 2)
    return decode_offset(int(ipaddress.ip_address(address)) - int(net.network_address),
                         get_max_bits(width, height), width, height)


def free_address(dataset, prefix):
    used = {ip['address'].split('/')[0] for ip in dataset['ip_addresses']}
    return next(str(a) for a in ipaddress.ip_network(prefix).hosts() if str(a) not in used)


@pytest.mark.parametrize("dpr", [1, 2])
def test_zoom_is_whole_device_pixels_per_cell(open_page, dpr):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20', device_scale_factor=dpr)
    wait_for_map(page)
    natural, css_width = page.eval_on_selector(
        '#map-img', 'img => [img.naturalWidth, img.getBoundingClientRect().width]')
    cells = natural / CELL_SIZE
    c = css_width * dpr / cells  # device pixels per cell
    assert c == int(c) >= CELL_SIZE
    page.click('#zoom-in')
    c2 = page.eval_on_selector('#map-img', 'img => img.getBoundingClientRect().width') * dpr / cells
    assert c2 == int(c2) > c
    assert page.inner_text('#zoom-level') == f'{float(f"{c2 / CELL_SIZE:.2f}"):g}×'
    assert page.errors == []


def test_zoom_steps(open_page):
    """Zoom out to 0.25 x, then in: 1, 2, 4, 5, 6, 7, 8, 10, 12 device pixels per cell, and back down the same way."""
    page = open_page(f'{BASE}/map/1/10_20_48_0_20', viewport=(1400, 900))
    wait_for_map(page)
    for _ in range(30):
        page.keyboard.press('-')
    assert page.is_disabled('#zoom-out')
    seen = [page.evaluate('window.__prefixMap.c')]
    for _ in range(8):
        page.keyboard.press('+')
        seen.append(page.evaluate('window.__prefixMap.c'))
    assert seen == [1, 2, 4, 5, 6, 7, 8, 10, 12] if CELL_SIZE == 4 else seen == sorted(set(seen))
    assert seen[0] == 1
    for _ in range(8):
        page.keyboard.press('-')
    assert page.evaluate('window.__prefixMap.c') == seen[0]


@pytest.mark.parametrize("dpr", [1, 2])
def test_ctrl_wheel_zooms_about_the_pointer(open_page, dpr):
    """Once the map overflows the view, the cell under the pointer stays under it (a centred map stays centred)."""
    page = open_page(f'{BASE}/map/1/10_20_48_0_20', device_scale_factor=dpr, viewport=(1200, 800))
    wait_for_map(page)
    for _ in range(4):
        page.keyboard.press('+')
    addr = '10.20.60.0'  # the middle cell of the /20
    x, y = cell_center(page, *cell_of('10.20.48.0/20', addr))
    page.mouse.move(x, y)
    assert page.inner_text('#insp-detail .big').startswith(addr + '/')
    c0 = page.evaluate('window.__prefixMap.c')
    page.keyboard.down('Control')
    for _ in range(3):
        page.mouse.wheel(0, -100)
    page.keyboard.up('Control')
    c1 = page.evaluate('window.__prefixMap.c')
    assert c1 > c0
    page.mouse.move(x + 1, y)
    page.mouse.move(x, y)
    assert page.inner_text('#insp-detail .big').startswith(addr + '/'), "the cell under the pointer stays"
    page.keyboard.down('Control')
    page.mouse.wheel(0, 100)
    page.keyboard.up('Control')
    c2 = page.evaluate('window.__prefixMap.c')
    assert c2 < c1
    page.mouse.move(x + 1, y)
    page.mouse.move(x, y)
    assert page.inner_text('#insp-detail .big').startswith(addr + '/')
    page.mouse.wheel(0, 100)
    assert page.evaluate('window.__prefixMap.c') == c2, "the plain wheel scrolls, it does not zoom"
    assert page.errors == []


def test_drag_pans_and_does_not_pin(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20', viewport=(1200, 800))
    wait_for_map(page)
    for _ in range(6):
        page.keyboard.press('+')
    before = page.eval_on_selector('#viewport', 'v => [v.scrollLeft, v.scrollTop]')
    vp = page.locator('#viewport').bounding_box()
    x, y = vp['x'] + vp['width'] / 2, vp['y'] + vp['height'] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x - 60, y - 40, steps=5)
    assert 'dragging' in page.get_attribute('#viewport', 'class')
    page.mouse.up()
    after = page.eval_on_selector('#viewport', 'v => [v.scrollLeft, v.scrollTop]')
    assert [round(a - b) for a, b in zip(after, before)] == [60, 40]
    assert 'focus=' not in page.url and 'dragging' not in (page.get_attribute('#viewport', 'class') or '')
    page.mouse.click(x, y)
    assert 'focus=' in page.evaluate('location.href'), "a click still pins"
    assert page.errors == []


@pytest.mark.parametrize("dpr", [1, 2])
def test_fit_goes_below_1x(open_page, dpr):
    """A /8 layered map (256 x 256 cells, 1024 device px at 1 x) fits a small window."""
    page = open_page(f'{BASE}/map/1/10_0_0_0_8', device_scale_factor=dpr, viewport=(1000, 700))
    wait_for_map(page)
    c = page.evaluate('window.__prefixMap.c')
    img, vp = page.evaluate("""() => ["map-img", "viewport"].map(id => {
        const r = document.getElementById(id).getBoundingClientRect();
        return [r.left, r.top, r.right, r.bottom];
    })""")
    assert img[0] >= vp[0] and img[1] >= vp[1] and img[2] <= vp[2] and img[3] <= vp[3], "the map is inside the view"
    assert c < CELL_SIZE
    assert page.inner_text('#zoom-level') == f'{float(f"{c / CELL_SIZE:.2f}"):g}×'
    assert page.eval_on_selector('#map-img', 'i => getComputedStyle(i).imageRendering') == 'auto'
    page.mouse.move(*cell_center(page, *layer_cell('10.0.0.0/8', 24, '10.20.0.0')))
    assert '10.20.0.0/24' in page.inner_text('#insp-detail')
    page.keyboard.press('+')
    while page.evaluate('window.__prefixMap.c') < CELL_SIZE:
        page.keyboard.press('+')
    assert page.eval_on_selector('#map-img', 'i => getComputedStyle(i).imageRendering') == 'pixelated'
    assert page.errors == []


@pytest.mark.parametrize("dpr", [1, 2])
def test_overlays_align_to_cell_edges(open_page, dpr):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20', device_scale_factor=dpr)
    wait_for_map(page)
    page.mouse.move(*cell_center(page, 5, 3))
    boxes = page.evaluate('''() => {
        const img = document.getElementById("map-img").getBoundingClientRect();
        return ["ov-hover", "ov-prefix"].map(id => {
            const r = document.getElementById(id).getBoundingClientRect();
            return [r.left - img.left, r.top - img.top, r.width, r.height];
        });
    }''')
    k = page.evaluate('window.__prefixMap.k')
    unit = CELL_SIZE * k  # device pixels per cell
    for box in boxes:
        for v in box:
            assert abs(v * dpr / unit - round(v * dpr / unit)) < 1e-6, (box, unit)
    left, top, width, height = boxes[0]
    assert (round(left * dpr / unit), round(top * dpr / unit), round(width * dpr / unit)) == (5, 3, 1)


def test_hover_shows_ip_and_prefix_chain(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20')
    wait_for_map(page)
    page.mouse.move(*cell_center(page, *cell_of('10.20.48.0/20', '10.20.48.1')))
    text = page.inner_text('#insp-detail')
    assert '10.20.48.1' in text and 'Anycast' in text and 'gw-48.example.test' in text
    assert 'Double-click to open map of 10.20.48.0/24' in text
    chain = page.eval_on_selector_all('ol.chain .p', 'els => els.map(e => e.textContent)')
    assert chain == ['10.0.0.0/8', '10.20.0.0/16', '10.20.0.0/17', '10.20.48.0/20', '10.20.48.0/24']
    assert page.is_visible('#ov-hover') and page.is_visible('#ov-prefix')
    assert page.is_hidden('#insp-summary')
    page.mouse.move(5, 5)
    assert page.is_visible('#insp-summary') and page.is_hidden('#ov-hover')
    assert page.errors == []


def test_free_cell(open_page, dataset):
    free = free_address(dataset, '10.20.48.0/24')
    page = open_page(f'{BASE}/map/1/10_20_48_0_20')
    wait_for_map(page)
    page.mouse.move(*cell_center(page, *cell_of('10.20.48.0/20', free)))
    assert page.inner_text('#insp-detail .big').startswith(free + '/')
    assert page.inner_text('#insp-detail .pill') == 'Free'
    add = page.get_attribute('#insp-detail a[href*="/ip-addresses/add/"]', 'href')
    assert add == f'{NETBOX}/ipam/ip-addresses/add/?address={free}/24&vrf=1'


def test_click_pins_and_escape_unpins(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20')
    wait_for_map(page)
    page.mouse.click(*cell_center(page, *cell_of('10.20.48.0/20', '10.20.48.1')))
    page.mouse.move(*cell_center(page, 20, 20))
    assert '10.20.48.1/' in page.inner_text('#insp-detail .big')
    assert page.is_visible('.pin-badge') and page.is_visible('#ov-pin')
    page.keyboard.press('Escape')
    assert page.is_hidden('#ov-pin')
    assert '10.20.48.1/' not in page.inner_text('#insp-detail .big')
    page.mouse.click(*cell_center(page, 20, 20))
    page.mouse.click(*cell_center(page, 20, 20))
    assert page.is_hidden('#ov-pin'), "second click on the pinned cell unpins"


def test_double_click_drills_down(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20')
    wait_for_map(page)
    # The first click pins and rewrites ?focus= in place; wait for the real navigation
    with page.expect_navigation(url=f'**{BASE}/map/1/10_20_48_0_24'):
        page.mouse.dblclick(*cell_center(page, *cell_of('10.20.48.0/20', '10.20.48.1')))


def test_double_click_in_leaf_opens_ip_in_netbox(open_page, dataset):
    page = open_page(f'{BASE}/map/1/10_20_48_0_24')
    wait_for_map(page)
    page.context.route(f'{NETBOX}/**', lambda route: route.fulfill(body='netbox'))
    ip = next(ip for ip in dataset['ip_addresses'] if ip['address'].startswith('10.20.48.1/'))
    with page.expect_popup() as popup:
        page.mouse.dblclick(*cell_center(page, *cell_of('10.20.48.0/24', '10.20.48.1')))
    assert popup.value.url == f'{NETBOX}/ipam/ip-addresses/{ip["id"]}/'


def test_free_blocks_are_free_and_aligned(open_page, dataset):
    page = open_page(f'{BASE}/map/1/10_20_48_0_24')
    wait_for_map(page)
    rows = page.eval_on_selector_all('#sum-free table.free td:first-child', 'els => els.map(e => e.textContent)')
    assert rows
    used = {ipaddress.ip_address(ip['address'].split('/')[0]) for ip in dataset['ip_addresses']}
    children = [ipaddress.ip_network(p['prefix']) for p in dataset['prefixes']
                if p['vrf'] == 1 and ':' not in p['prefix']
                and ipaddress.ip_network(p['prefix']).subnet_of(ipaddress.ip_network('10.20.48.0/24'))
                and p['prefix'] != '10.20.48.0/24']
    sizes = []
    for row in rows:
        block = ipaddress.ip_network(row)  # raises on unaligned blocks
        assert not any(a in block for a in used), row
        assert not any(block.overlaps(c) for c in children), row
        sizes.append(block.num_addresses)
    assert sizes == sorted(sizes, reverse=True)


def free_block_rows(page, where='#sum-free'):
    return [ipaddress.ip_network(r) for r in
            page.eval_on_selector_all(f'{where} table.free td:first-child', 'els => els.map(e => e.textContent)')]


def test_network_and_broadcast_are_not_free(open_page, dataset):
    page = open_page(f'{BASE}/map/1/10_20_50_0_24')
    wait_for_map(page)
    edges = [ipaddress.ip_address('10.20.50.0'), ipaddress.ip_address('10.20.50.255')]
    rows = free_block_rows(page)
    assert rows and not any(e in block for block in rows for e in edges)
    used = {ip['address'].split('/')[0] for ip in dataset['ip_addresses']}
    assert '10.20.50.255' not in used
    page.mouse.move(*cell_center(page, *cell_of('10.20.50.0/24', '10.20.50.255')))
    assert page.inner_text('#insp-detail .pill') == 'Broadcast address'
    assert page.locator('#insp-detail a[href*="/ip-addresses/add/"]').count() == 0


def test_pool_edges_are_usable(open_page, dataset):
    """NetBox pools have no network or broadcast address."""
    page = open_page(f'{BASE}/map/1/10_20_36_128_26')
    wait_for_map(page)
    used = {ip['address'].split('/')[0] for ip in dataset['ip_addresses']}
    rows = free_block_rows(page)
    for edge in ('10.20.36.128', '10.20.36.191'):
        if edge not in used:
            assert any(ipaddress.ip_address(edge) in block for block in rows), edge


def test_legend_without_tenants_has_no_stray_text(open_page):
    page = open_page(f'{BASE}/map/None/172_31_4_0_24')
    wait_for_map(page)
    assert 'null' not in page.inner_text('#legend')


def test_legend_lists_ip_statuses_of_the_map(open_page):
    page = open_page(f'{BASE}/map/1/10_20_0_0_17')
    wait_for_map(page)
    legend = page.inner_text('#legend')
    for label in ('In use', 'DHCP', 'Reserved, deprecated', 'With role'):
        assert label in legend


def test_tree_shows_path_and_expands_lazily(open_page, server):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20')
    page.wait_for_selector('#tree .row.current')
    path = page.eval_on_selector_all('#tree .row:has(.tog[aria-expanded="true"]) .pfx',
                                     'els => els.map(e => e.textContent)')
    assert path == ['10.0.0.0/8', '10.20.0.0/16', '10.20.0.0/17', '10.20.48.0/20']
    assert page.inner_text('#tree .row.current .pfx') == '10.20.48.0/20'
    requests = []
    page.on('request', lambda r: requests.append(r.url))
    collapsed = page.query_selector('#tree .tog[aria-expanded="false"]')
    collapsed.click()
    assert collapsed.get_attribute('aria-expanded') == 'true'
    page.wait_for_function('!document.querySelector("#tree .msg")')
    assert requests and all(url.endswith('?nav=1') for url in requests if '/data/' in url)
    links = page.eval_on_selector_all('#tree a', 'els => els.map(e => e.getAttribute("href"))')
    assert len(links) > 10
    for link in links:
        assert page.request.get(server + link).status == 200, link
    assert page.errors == []


def test_tree_and_map_highlight_each_other(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20')
    wait_for_map(page)
    page.wait_for_selector('#tree .row.current')
    page.hover('#tree .row[data-prefix="10.20.49.0/24"]')
    assert page.is_visible('#ov-select')
    page.mouse.move(*cell_center(page, *cell_of('10.20.48.0/20', '10.20.48.1')))
    assert page.get_attribute('#tree .row.trace', 'data-prefix') == '10.20.48.0/24'


def test_collapsing_panels_lets_fit_grow(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20', device_scale_factor=2, viewport=(1440, 1600))
    wait_for_map(page)
    k = page.evaluate('window.__prefixMap.k')
    page.click('#zoom [data-toggle-panel="tree"]')
    page.keyboard.press(']')
    assert page.evaluate('document.body.className').split() == ['map-page', 'no-tree', 'no-insp']
    page.wait_for_function(f'window.__prefixMap.k > {k}')
    page.reload()
    wait_for_map(page)
    assert page.is_hidden('#tree-panel') and page.is_hidden('#insp-panel'), "panel state persists"
    page.click('#zoom [data-toggle-panel="tree"]')
    assert page.is_visible('#tree-panel')


def test_freshness_dot(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20')
    wait_for_map(page)
    page.wait_for_function('document.getElementById("fresh").classList.contains("ok")')
    assert page.inner_text('#fresh-text').startswith('updated ')

    def failing(route):
        route.fulfill(json={'status': 'ok', 'update_running': False, 'last_success_at': None,
                            'data_age_seconds': None, 'last_error': 'ConnectionError: NetBox unreachable'})
    page2 = open_page(f'{BASE}/map/1/10_20_48_0_20', route=(f'**{BASE}/healthz', failing))
    wait_for_map(page2)
    page2.wait_for_function('document.getElementById("fresh").classList.contains("stale")')
    assert 'NetBox unreachable' in page2.get_attribute('#fresh', 'title')


def test_search_pins_address_in_map(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20')
    wait_for_map(page)
    page.keyboard.press('/')
    page.keyboard.type('10.20.48.1')
    assert page.is_visible('#ov-pin')
    assert 'pinned' not in page.inner_text('#search-msg')
    page.fill('#search', '10.20.49.0/24')
    assert page.is_visible('#ov-select')
    with page.expect_navigation():
        page.press('#search', 'Enter')
    assert page.url.endswith(f'{BASE}/map/1/10_20_49_0_24')


def layer_cell(prefix, block_len, address):
    net = ipaddress.ip_network(prefix)
    bits = block_len - net.prefixlen
    width, height = 2 ** (bits - bits // 2), 2 ** (bits // 2)
    index = (int(ipaddress.ip_address(address)) - int(net.network_address)) >> (32 - block_len)
    return decode_offset(index, get_max_bits(width, height), width, height)


def test_layered_map_hover_and_drill_down(open_page):
    page = open_page(f'{BASE}/map/1/10_0_0_0_8')
    wait_for_map(page)
    assert page.inner_text('#tree .row.current .pfx') == '10.0.0.0/8'
    assert '6,111 / 16,777,216 used' in page.inner_text('#legend') and '1 cell = /24' in page.inner_text('#legend')
    page.mouse.move(*cell_center(page, *layer_cell('10.0.0.0/8', 24, '10.20.0.0')))
    detail = page.inner_text('#insp-detail')
    assert '10.20.0.0/24' in detail and '134 used' in detail
    assert 'Double-click to open map of 10.20.0.0/16' in detail
    inside = page.eval_on_selector_all('#insp-detail section:has-text("Prefixes in this block") .p',
                                       'els => els.map(e => e.textContent)')
    assert inside == ['10.20.0.64/26', '10.20.0.192/28']
    page.mouse.move(*cell_center(page, *layer_cell('10.0.0.0/8', 24, '10.99.0.0')))
    assert 'No prefix in this block' in page.inner_text('#insp-detail')
    with page.expect_navigation(url=f'**{BASE}/map/1/10_30_0_0_16'):
        page.mouse.dblclick(*cell_center(page, *layer_cell('10.0.0.0/8', 24, '10.30.7.0')))
    assert page.errors == []


@pytest.mark.parametrize("dpr", [1, 2])
def test_layered_overlays_align(open_page, dpr):
    page = open_page(f'{BASE}/map/1/10_0_0_0_8', device_scale_factor=dpr)
    wait_for_map(page)
    page.mouse.move(*cell_center(page, *layer_cell('10.0.0.0/8', 24, '10.30.7.0')))
    k = page.evaluate('window.__prefixMap.k')
    unit = CELL_SIZE * k
    boxes = page.evaluate("""() => {
        const img = document.getElementById("map-img").getBoundingClientRect();
        return ["ov-hover", "ov-prefix"].map(id => {
            const r = document.getElementById(id).getBoundingClientRect();
            return [r.left - img.left, r.top - img.top, r.width, r.height].map(v => v * devicePixelRatio);
        });
    }""")
    hover, prefix = [[round(v / unit, 6) for v in box] for box in boxes]
    x, y = layer_cell('10.0.0.0/8', 24, '10.30.7.0')
    assert hover == [x, y, 1, 1]
    x0, y0 = layer_cell('10.0.0.0/8', 24, '10.30.0.0')
    assert prefix == [x0, y0, 16, 16], "the /16 child covers 16x16 cells"


def test_layered_search_pins_block(open_page):
    page = open_page(f'{BASE}/map/1/10_0_0_0_8?focus=10.20.48.1')
    wait_for_map(page)
    assert page.is_visible('#ov-pin')
    assert '10.20.48.0/24' in page.inner_text('#insp-detail .big')
    page.fill('#search', '10.30.1.1')
    assert 'block 10.30.1.0/24' in page.inner_text('#search-msg')


def test_search_outside_map_uses_server(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_24')
    wait_for_map(page)
    page.fill('#search', '10.20.0.1')
    page.wait_for_selector('#search-msg li')
    assert '10.20.0.0/24' in page.inner_text('#search-msg li >> nth=0')
    assert 'gw-0.example.test' in page.inner_text('#search-msg li >> nth=0')
    with page.expect_navigation():
        page.press('#search', 'Enter')
    assert page.url.endswith(f'{BASE}/map/1/10_20_0_0_24?focus=10.20.0.1')
    wait_for_map(page)
    assert page.is_visible('#ov-pin')
    assert '10.20.0.1/' in page.inner_text('#insp-detail .big')


def test_search_from_index_page(open_page):
    page = open_page(f'{BASE}/')
    page.keyboard.press('/')
    page.keyboard.type('192.168.0.0/24')
    page.wait_for_selector('#search-msg li a')
    assert page.get_attribute('#search-msg li a', 'href') == f'{BASE}/map/None/192_168_0_0_24'
    page.fill('#search', '300.1.1.1')
    page.press('#search', 'Enter')
    page.wait_for_function('document.getElementById("search").classList.contains("bad")')
    page.fill('#search', '8.8.8.8')
    page.wait_for_function('document.getElementById("search-msg").textContent.includes("no prefix")')
    assert page.errors == [] or all('400' in e for e in page.errors)


def test_focus_parameter_outlines_prefix(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_24?focus=10.20.48.128/25')
    wait_for_map(page)
    assert page.is_visible('#ov-select')
    box = page.evaluate("""() => {
        const s = document.getElementById("ov-select").getBoundingClientRect();
        const i = document.getElementById("map-img").getBoundingClientRect();
        return (s.width * s.height) / (i.width * i.height);
    }""")
    assert box == 0.5


def test_old_data_file_without_usage(open_page):
    def strip(route):
        data = route.fetch().json()
        route.fulfill(json={k: data[k] for k in ('prefix', 'child_prefixes', 'ip_addresses')})

    page = open_page(f'{BASE}/map/1/10_0_0_0_8', route=(f'**{BASE}/data/1/10_0_0_0_8', strip))
    wait_for_map(page)
    assert '16,777,216 addresses' in page.inner_text('#legend')
    assert page.inner_text('#sum-usage .stat b >> nth=0') == '—'
    page.mouse.move(*cell_center(page, *layer_cell('10.0.0.0/8', 24, '10.20.0.0')))
    assert '10.20.0.0/24' in page.inner_text('#insp-detail') and 'IPs unknown' in page.inner_text('#insp-detail')
    assert page.locator('#insp-detail table.free').count() == 0 and page.locator('#sum-free *').count() == 0
    assert page.errors == []


def test_free_block_highlight_cleared_on_rerender(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_24')
    wait_for_map(page)
    page.mouse.click(*cell_center(page, 0, 0))
    page.hover('#insp-detail table.free tr >> nth=0')
    assert page.is_visible('#ov-free')
    page.keyboard.press('Escape')
    # The summary may put another free-block row under the pointer; only that one may be highlighted
    assert page.is_hidden('#ov-free') or page.locator('#sum-free table.free tr:hover').count() == 1


@pytest.mark.parametrize("path", ['/', '/help', '/map/1', '/map/None', '/map/1/10_0_0_0_8', '/map/None/172_31_0_0_16',
                                  '/map/None/172_31_4_0_24'])
def test_pages_have_no_script_errors(open_page, path):
    page = open_page(BASE + path)
    page.wait_for_load_state('networkidle')
    assert page.errors == []


def test_data_file_from_older_version(open_page):
    """Pages can be served before the first update rewrites old data files."""
    def strip_new_fields(route):
        data = route.fetch().json()
        old = {k: data[k] for k in ('prefix', 'child_prefixes')}
        old['ip_addresses'] = [{k: ip[k] for k in ('id', 'address', 'vrf', 'tenant')} for ip in data['ip_addresses']]
        route.fulfill(json=old)

    page = open_page(f'{BASE}/map/1/10_20_48_0_20', route=(f'**{BASE}/data/1/10_20_48_0_20', strip_new_fields))
    wait_for_map(page)
    page.mouse.move(*cell_center(page, *cell_of('10.20.48.0/20', '10.20.48.1')))
    assert '10.20.48.1' in page.inner_text('#insp-detail')
    assert page.errors == []


def test_user_text_is_escaped(open_page):
    evil = '<img src=x onerror="window.pwned=1">'

    def inject(route):
        data = route.fetch().json()
        for p in data.get('nested_prefixes', []) + data['child_prefixes']:
            p['description'] = evil
        for ip in data.get('ip_addresses', []):
            ip['dns_name'] = evil
            ip['description'] = evil
        route.fulfill(json=data)

    page = open_page(f'{BASE}/map/1/10_20_48_0_20', route=(f'**{BASE}/data/**', inject))
    wait_for_map(page)
    page.wait_for_selector('#tree .row.current')
    page.mouse.move(*cell_center(page, *cell_of('10.20.48.0/20', '10.20.48.1')))
    assert evil in page.inner_text('#insp-detail')
    assert page.evaluate('window.pwned') is None
    assert page.locator('img[src="x"]').count() == 0


def test_map_hidden_until_first_layout(open_page):
    """The image must not flash at its natural size while the data file loads."""
    held = []
    page = open_page(f'{BASE}/map/1/10_20_48_0_20', device_scale_factor=2,
                     route=(f'**{BASE}/data/1/10_20_48_0_20', lambda r: held.append(r)))
    page.wait_for_function('document.getElementById("map-img").complete')
    assert held, "data request is held"
    assert page.eval_on_selector('#stage', 'e => getComputedStyle(e).visibility') == 'hidden'
    held[0].continue_()
    wait_for_map(page)
    assert page.eval_on_selector('#stage', 'e => getComputedStyle(e).visibility') == 'visible'


def test_pin_is_kept_in_url(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20')
    wait_for_map(page)
    page.mouse.click(*cell_center(page, *cell_of('10.20.48.0/20', '10.20.49.7')))
    # page.url can lag behind history.replaceState(); read the location itself
    assert page.evaluate('location.href').endswith('/map/1/10_20_48_0_20?focus=10.20.49.7')
    page.reload()
    wait_for_map(page)
    assert page.inner_text('#insp-detail .big').startswith('10.20.49.7/')
    page.keyboard.press('Escape')
    assert page.evaluate('location.href').endswith('/map/1/10_20_48_0_20')


def test_arrow_keys_move_pin_and_enter_opens(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20')
    wait_for_map(page)
    page.mouse.click(*cell_center(page, 0, 0))
    page.mouse.move(0, 0)
    page.keyboard.press('ArrowRight')  # Morton order: x=1, y=0 is offset 1
    assert page.inner_text('#insp-detail .big').startswith('10.20.48.1/')
    page.keyboard.press('ArrowDown')  # x=1, y=1 is offset 3
    assert page.inner_text('#insp-detail .big').startswith('10.20.48.3/')
    page.keyboard.press('Shift+ArrowRight')  # x=17, y=1: the next /24
    assert page.inner_text('#insp-detail .big').startswith('10.20.49.3/')
    page.keyboard.press('ArrowLeft')
    page.keyboard.press('ArrowLeft')
    assert page.evaluate('location.href').endswith('?focus=10.20.48.87')  # x=15, y=1: back in 10.20.48.0/24
    with page.expect_navigation(url=f'**{BASE}/map/1/10_20_48_0_24'):
        page.keyboard.press('Enter')


def test_copy_address_and_free_block(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_24')
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
    wait_for_map(page)
    page.mouse.click(*cell_center(page, *cell_of('10.20.48.0/24', '10.20.48.9')))
    page.keyboard.press('c')
    assert page.evaluate('navigator.clipboard.readText()') == '10.20.48.9'
    assert page.inner_text('#toast') == 'Copied 10.20.48.9'
    first = page.inner_text('#insp-detail table.free tr >> nth=0 >> td >> nth=0')
    page.click('#insp-detail table.free tr >> nth=0 >> button.copy')
    assert page.evaluate('navigator.clipboard.readText()') == first


def test_free_blocks_of_one_size(open_page, dataset):
    page = open_page(f'{BASE}/map/1/10_20_0_0_17')
    wait_for_map(page)
    page.select_option('#sum-free select', '26')
    rows = free_block_rows(page)
    assert rows and all(r.prefixlen == 26 for r in rows)
    assert rows == sorted(rows)
    used = {ipaddress.ip_address(ip['address'].split('/')[0]) for ip in dataset['ip_addresses'] if ip['vrf'] == 1}
    children = [ipaddress.ip_network(p['prefix']) for p in dataset['prefixes'] if p['vrf'] == 1
                and ':' not in p['prefix'] and ipaddress.ip_network(p['prefix']).prefixlen > 17
                and ipaddress.ip_network(p['prefix']).subnet_of(ipaddress.ip_network('10.20.0.0/17'))]
    for r in rows:
        assert not any(a in r for a in used) and not any(r.overlaps(c) for c in children), r
    assert '× /26' in page.inner_text('#sum-free h3')
    page.reload()
    wait_for_map(page)
    assert page.input_value('#sum-free select') == '26'


def export_svg(page, mono=False):
    import xml.etree.ElementTree as ET
    svg = page.evaluate(f'PrefixMapExport.build({{mono: {"true" if mono else "false"}}})')
    return svg, ET.fromstring(svg)  # raises on malformed XML


SVG_NS = '{http://www.w3.org/2000/svg}'


def test_svg_export_has_a_cell_per_ip_and_a_legend(open_page, dataset):
    page = open_page(f'{BASE}/map/1/10_20_50_0_24')
    wait_for_map(page)
    svg, root = export_svg(page)
    ips = [ip for ip in dataset['ip_addresses'] if ip['vrf'] == 1
           and ipaddress.ip_address(ip['address'].split('/')[0]) in ipaddress.ip_network('10.20.50.0/24')]
    cell_groups = [g for g in root.iter(SVG_NS + 'g') if g.get('fill-opacity')]
    assert sum(len(g.findall(SVG_NS + 'rect')) for g in cell_groups) == len(ips)
    texts = [t.text for t in root.iter(SVG_NS + 'text')]
    assert texts[0].startswith('10.20.50.0/24 · VRF LAN')
    for label in ('In use', 'Printers'):
        assert label in texts
    assert 'url(#t0)' not in svg


def hatches_of(root):
    """Hatch number of each hatched prefix rectangle: the hatch paths follow their rectangle."""
    out, last = {}, None
    body = next(g for g in root.iter(SVG_NS + 'g') if (g.get('transform') or '').startswith('translate'))
    for e in body.iter():
        if e.tag == SVG_NS + 'rect' and e.find(SVG_NS + 'title') is not None:
            last = e.find(SVG_NS + 'title').text
        elif e.tag == SVG_NS + 'path' and (e.get('class') or '').startswith('hatch-') and last:
            out[last] = int(e.get('class').split('-')[1])
    return out


def test_svg_export_black_and_white_hatches_tenants(open_page, dataset):
    """Tenants get vector hatches, no SVG patterns: Chromium prints patterns as bitmaps."""
    page = open_page(f'{BASE}/map/1/10_20_0_0_17')
    wait_for_map(page)
    svg, root = export_svg(page, mono=True)
    assert '<pattern' not in svg
    hatches = hatches_of(root)
    tenants = {p['prefix']: p['tenant'] for p in dataset['prefixes'] if p['vrf'] == 1}
    by_tenant = {}
    for prefix, n in hatches.items():
        by_tenant.setdefault(tenants[prefix], set()).add(n)
    assert len(by_tenant) == 8 and all(len(v) == 1 for v in by_tenant.values()), "one hatch per tenant"
    assert len({min(v) for v in by_tenant.values()}) == 8, "eight tenants, eight hatches"
    untenanted = [r for r in root.iter(SVG_NS + 'rect') if r.find(SVG_NS + 'title') is not None
                  and not tenants.get(r.find(SVG_NS + 'title').text)]
    assert untenanted and all(r.get('fill') == 'none' for r in untenanted)


def test_svg_export_has_no_patterns(open_page):
    for path in ('10_0_0_0_8', '10_20_0_0_17'):
        page = open_page(f'{BASE}/map/1/{path}')
        wait_for_map(page)
        for mono in (False, True):
            svg, _ = export_svg(page, mono=mono)
            assert '<pattern' not in svg and 'url(#' not in svg, (path, mono)


def retenant(mapping):
    """Route handler that sets the tenant (and its colour) of nested prefixes: {prefix: (tenant, color)}."""
    def handle(route):
        data = route.fetch().json()
        for p in data['nested_prefixes']:
            if p['prefix'] in mapping:
                p['tenant'], p['color'] = mapping[p['prefix']]
        route.fulfill(json=data)
    return handle


def test_legend_does_not_describe_shared_colours(open_page):
    """Tenants 16 ids apart share a colour; the legend lists both by name and adds nothing about it."""
    route = retenant({'10.20.0.64/26': (17, '#8fbbd9')})  # colour of tenant 1, Core
    page = open_page(f'{BASE}/map/1/10_20_0_0_17', route=(f'**{BASE}/data/1/10_20_0_0_17', route))
    wait_for_map(page)
    names = page.eval_on_selector_all('#legend .tenant-toggle', 'els => els.map(e => e.textContent)')
    assert 'Core' in names and 'Tenant 17' in names
    assert 'same' not in page.inner_text('#legend').lower()
    titles = page.eval_on_selector_all('#legend [title]', 'els => els.map(e => e.title)')
    assert all('same' not in t.lower() for t in titles)
    for mono in (False, True):
        _, root = export_svg(page, mono=mono)
        assert not any('same' in (t.text or '').lower() for t in root.iter(SVG_NS + 'text'))
    assert page.errors == []


def test_svg_export_black_and_white_has_16_distinct_hatches(open_page, output_dir):
    with open(os.path.join(output_dir, 'data-1-10_20_0_0_17.json')) as f:
        nested = json.load(f)['nested_prefixes']
    mapping = {p['prefix']: (i + 1, '#123456') for i, p in enumerate(nested[:17])}
    page = open_page(f'{BASE}/map/1/10_20_0_0_17', route=(f'**{BASE}/data/1/10_20_0_0_17', retenant(mapping)))
    wait_for_map(page)
    _, root = export_svg(page, mono=True)
    hatches = hatches_of(root)
    assert set(hatches.values()) == set(range(16)), "17 tenants use all 16 hatches"


def test_reserved_prefix_in_legend_chain_and_svg(open_page):
    page = open_page(f'{BASE}/map/1/10_20_0_0_17')
    wait_for_map(page)
    assert page.locator('#legend .lg:has(.sw.striped)').inner_text() == 'Reserved, deprecated prefix'
    page.mouse.move(*cell_center(page, *cell_of('10.20.0.0/17', '10.20.5.200')))
    assert page.inner_text('#insp-detail .chain li.inner .d').startswith('reserved · ')
    for mono in (False, True):
        svg, root = export_svg(page, mono=mono)
        assert len(root.findall(f'.//{SVG_NS}path[@class="striped"]')) == 1
        assert 'Reserved, deprecated prefix' in svg
    page = open_page(f'{BASE}/map/1/10_20_48_0_24')
    wait_for_map(page)
    assert page.locator('#legend .sw.striped').count() == 0
    assert page.errors == []


def test_legend_tenant_outlines_its_prefixes(open_page, output_dir):
    with open(os.path.join(output_dir, 'data-1-10_20_0_0_17.json')) as f:
        nested = [ipaddress.ip_network(p['prefix']) for p in json.load(f)['nested_prefixes'] if p['tenant'] == 2]
    outermost = {str(n) for n in nested if not any(o != n and n.subnet_of(o) for o in nested)}
    page = open_page(f'{BASE}/map/1/10_20_0_0_17')
    wait_for_map(page)
    office = page.locator('#legend .tenant-toggle', has_text='Office')
    office.click()
    assert office.get_attribute('aria-pressed') == 'true'
    titles = page.eval_on_selector_all('#ov-tenant .ov-tenant', 'els => els.map(e => e.title)')
    assert set(titles) == outermost and len(titles) == len(outermost) > 1
    assert page.is_hidden('#toast'), "the outline is the feedback"
    page.keyboard.press('+')
    box = page.eval_on_selector('#ov-tenant .ov-tenant', 'e => e.getBoundingClientRect().width')
    assert box > 0
    office.click()
    assert page.is_hidden('#ov-tenant') and office.get_attribute('aria-pressed') == 'false'
    page.locator('#legend .tenant-toggle', has_text='Lab').focus()
    page.keyboard.press('Enter')
    assert page.locator('#ov-tenant .ov-tenant').count() >= 1
    assert page.errors == []


def test_free_search_matches_the_map_and_opens_it(open_page, server):
    """The server finds as many free /26 in the /17 as the map page lists, and Enter opens the first one."""
    import urllib.request
    with urllib.request.urlopen(f'{server}{BASE}/search?q=free%20/26%20in%2010.20.0.0/17') as r:
        body = json.load(r)
    page = open_page(f'{BASE}/map/1/10_20_0_0_17')
    wait_for_map(page)
    on_map = page.evaluate("""() => window.__prefixMap.freeBlocks('10.20.0.0/17').blocks
        .filter(b => b.len <= 26).reduce((s, b) => s + b.size / 64, 0)""")
    assert body['counts'] == {'LAN': on_map}
    page.fill('#search', 'free /26')
    page.wait_for_selector('#search-msg li')
    assert page.inner_text('#search-msg').startswith('Free: ')
    first = page.inner_text('#search-msg li a >> nth=0')
    assert first.endswith('/26')
    with page.expect_navigation():
        page.press('#search', 'Enter')
    assert page.url.endswith(f'?focus={first}')
    wait_for_map(page)
    assert page.is_visible('#ov-select')
    assert page.errors == []


def test_tenant_list_in_inspector_and_permalink(open_page):
    page = open_page(f'{BASE}/map/1/10_20_0_0_17')
    wait_for_map(page)
    page.locator('#legend .tenant-toggle', has_text='Office').click()
    assert page.evaluate('location.search') == '?tenant=2'
    section = page.locator('#sum-free section', has_text='Tenant Office')
    rows = section.locator('table.tenant-list tr td:first-child').all_inner_texts()
    outlined = page.eval_on_selector_all('#ov-tenant .ov-tenant', 'els => els.map(e => e.title)')
    assert rows == sorted(outlined, key=lambda p: ipaddress.ip_network(p)) and len(rows) > 1
    assert '% ' not in section.locator('h3').inner_text()  # usage is in the header, e.g. "1,234 / 9,000 · 14%"
    section.locator('tr', has_text='10.20.8.0/21').click()
    assert page.is_visible('#ov-select')
    assert 'focus=10.20.8.0%2F21' in page.url or 'focus=10.20.8.0/21' in page.url
    url = page.url
    page.goto(url)
    wait_for_map(page)
    assert page.locator('#ov-tenant .ov-tenant').count() == len(rows), "tenant outline restored from the URL"
    assert page.is_visible('#ov-select'), "focus restored too"
    page.locator('#sum-free button', has_text='Clear outline').click()
    assert page.is_hidden('#ov-tenant') and 'tenant=' not in page.url
    assert page.errors == []


def test_svg_export_of_layered_map(open_page):
    page = open_page(f'{BASE}/map/1/10_0_0_0_8')
    wait_for_map(page)
    svg, root = export_svg(page)
    assert '1 cell = /24' in svg
    assert root.get('viewBox').startswith('0 0 2560 ')


def test_svg_export_escapes_user_text(open_page):
    evil = '<b onclick="x">&</b>'

    def inject(route):
        html = route.fetch().text()
        # Only inside the page config: elsewhere the raw tag would be page markup, not text
        head, config = html.split('id="page-config">', 1)
        route.fulfill(body=head + 'id="page-config">' + config.replace('Storage block', json.dumps(evil)[1:-1]),
                      content_type='text/html')

    page = open_page(f'{BASE}/map/1/10_20_48_0_20', route=(f'**{BASE}/map/1/10_20_48_0_20', inject))
    wait_for_map(page)
    svg, root = export_svg(page)
    assert evil in next(root.iter(SVG_NS + 'text')).text


def test_print_shows_only_the_vector_map(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20')
    wait_for_map(page)
    page.evaluate('PrefixMapExport.preparePrint()')
    page.emulate_media(media='print')
    assert page.is_visible('#print-sheet svg')
    for hidden in ('#top', '#tree-panel', '#insp-panel', '#map-panel', '#legend'):
        assert page.is_hidden(hidden), hidden
    page.emulate_media(media='screen')
    assert page.is_hidden('#print-sheet') and page.is_visible('#map-img')


def test_free_space_inside_child_containers_counts_as_free(open_page):
    """10.20.128.0/17 is an empty container: its space is free on the /16 map."""
    page = open_page(f'{BASE}/map/1/10_20_0_0_16')
    wait_for_map(page)
    assert ipaddress.ip_network('10.20.128.0/17') in free_block_rows(page)


def test_pool_is_shown_in_inspector(open_page):
    page = open_page(f'{BASE}/map/1/10_20_36_0_24')
    wait_for_map(page)
    page.mouse.move(*cell_center(page, *cell_of('10.20.36.0/24', '10.20.36.128')))
    pills = page.eval_on_selector_all('#insp-detail .pill', 'els => els.map(e => e.textContent)')
    assert 'Pool' in pills and 'Network address' not in pills
    assert 'pool' in page.inner_text('#insp-detail ol.chain li.inner')


@pytest.mark.parametrize('path', ['/map/1/10_20_50_0_24', '/map/1/10_20_1_0_27', '/map/1/10_20_0_0_16'])
def test_svg_export_title_fits_the_map(open_page, path):
    page = open_page(BASE + path)
    wait_for_map(page)
    widths = page.evaluate('''() => {
        const host = document.createElement("div");
        host.innerHTML = PrefixMapExport.build({});
        document.body.append(host);
        const svg = host.querySelector("svg"), w = svg.viewBox.baseVal.width;
        const texts = [...svg.querySelectorAll("text")].slice(0, 2).map((t) => t.getComputedTextLength());
        const map = svg.querySelector("g[transform] > rect").width.baseVal.value;
        host.remove();
        return { w, texts, map };
    }''')
    assert all(t <= widths['w'] for t in widths['texts']), widths
    assert widths['map'] <= widths['w']


def test_ip_range_in_inspector_and_free_blocks(open_page, dataset):
    page = open_page(f'{BASE}/map/1/10_20_0_0_17')
    wait_for_map(page)
    blocks = [ipaddress.ip_network(b) for b in page.evaluate(
        '() => window.__prefixMap.freeBlocks("10.20.0.0/17").blocks.map((b) => '
        '[24, 16, 8, 0].map((s) => Math.floor(b.start / 2 ** s) % 256).join(".") + "/" + b.len)')]
    # 10.20.20.0/22 was free; 10.20.20.0/26 is now the planned range
    assert not any(b.overlaps(ipaddress.ip_network('10.20.20.0/26')) for b in blocks)
    assert ipaddress.ip_network('10.20.20.64/26') in blocks
    page.mouse.move(*cell_center(page, *cell_of('10.20.0.0/17', '10.20.20.5')))
    detail = page.inner_text('#insp-detail')
    assert 'IP range' in page.inner_text('#insp-detail .pill')
    assert '10.20.20.0 – 10.20.20.63' in detail and 'Printers, planned' in detail
    assert 'IP range' in page.inner_text('#legend')
    svg = page.evaluate('PrefixMapExport.build({})')
    assert '<g fill="#555">' in svg and 'IP range' in svg


def test_text_search_opens_the_address(open_page):
    page = open_page(f'{BASE}/')
    page.keyboard.press('/')
    page.keyboard.type('gw-93.')
    page.wait_for_selector('#search-msg li a')
    assert page.inner_text('#search-msg li a') == '10.20.93.1'
    with page.expect_navigation(url=f'**{BASE}/map/1/10_20_93_0_24?focus=10.20.93.1'):
        page.press('#search', 'Enter')
    wait_for_map(page)
    assert page.inner_text('#insp-detail .big').startswith('10.20.93.1/')


def test_addresses_with_several_records(open_page):
    def inject(route):
        data = route.fetch().json()
        if 'ip_addresses' in data and data['prefix'] == '10.20.48.0/24':
            first = data['ip_addresses'][0]
            data['ip_addresses'].append(dict(first, id=99999, vrf=None, status='reserved'))
        route.fulfill(json=data)

    page = open_page(f'{BASE}/map/1/10_20_48_0_24', route=(f'**{BASE}/data/**', inject))
    wait_for_map(page)
    assert 'addresses with several records' in page.inner_text('#sum-free').lower()
    page.click('#sum-free section:has-text("several records") tr >> nth=0')
    assert '2 records' in page.inner_text('#insp-detail .sub')
    detail = page.inner_text('#insp-detail')
    assert 'all records of this address' in detail.lower() and 'Global' in detail and 'LAN' in detail


def test_last_change_section_and_overlay(open_page):
    def inject(route):
        data = route.fetch().json()
        if data.get('prefix') == '10.20.48.0/24':
            data['changes'] = {'at': 1767225600, 'since': 1767139200, 'added': ['10.20.48.1'],
                               'removed': ['10.20.48.200'],
                               'changed': [], 'prefixes_added': [], 'prefixes_removed': [],
                               'added_count': 1, 'removed_count': 1, 'changed_count': 0,
                               'prefixes_added_count': 0, 'prefixes_removed_count': 0}
        route.fulfill(json=data)

    page = open_page(f'{BASE}/map/1/10_20_48_0_24', route=(f'**{BASE}/data/**', inject))
    wait_for_map(page)
    section = page.locator('#sum-free section:has-text("Last change")')
    assert '1 IP added · 1 removed' in section.inner_text()
    assert page.is_hidden('#ov-changes')
    page.check('#show-changes')
    assert page.locator('#ov-changes .ov-change.added').count() == 1
    assert page.locator('#ov-changes .ov-change.removed').count() == 1
    section.locator('tr >> nth=1').click()
    assert page.inner_text('#insp-detail .big').startswith('10.20.48.200/')


@pytest.mark.parametrize("dpr,presses", [(1, 2), (2, 1), (1, 5)])
def test_fractional_zoom_keeps_cells_identical(open_page, output_dir, dpr, presses):
    """
    At c device pixels per cell, device pixel i shows image pixel floor((i + 1/2) * cs / c) (nearest neighbour at the
    pixel centre). c device pixels hold exactly cs image pixels, so every cell gets the same pattern.
    """
    import io
    import numpy as np
    from PIL import Image
    page = open_page(f'{BASE}/map/1/10_20_48_0_24', device_scale_factor=dpr, viewport=(1400, 1400))
    wait_for_map(page)
    for _ in range(30):
        page.keyboard.press('-')
    while page.evaluate('window.__prefixMap.c') < CELL_SIZE:
        page.keyboard.press('+')
    for _ in range(presses):
        page.keyboard.press('+')
    c = page.evaluate('window.__prefixMap.c')
    shot = np.array(Image.open(io.BytesIO(page.locator('#map-img').screenshot())).convert('RGB')).astype(int)
    png = np.array(Image.open(f'{output_dir}/address_map-1-10_20_48_0_24.png').convert('RGB')).astype(int)
    rows = ((2 * np.arange(shot.shape[0]) + 1) * CELL_SIZE) // (2 * c)
    cols = ((2 * np.arange(shot.shape[1]) + 1) * CELL_SIZE) // (2 * c)
    expected = png[rows][:, cols]
    assert shot.shape[:2] == (png.shape[0] * c // CELL_SIZE, png.shape[1] * c // CELL_SIZE)
    assert (np.abs(shot - expected).max(axis=2) > 8).mean() < 0.001, f"c={c}"


def test_change_history_list(open_page):
    def record(at, added=(), removed=()):
        return {'at': at, 'since': at - 3600, 'added': list(added), 'removed': list(removed), 'changed': [],
                'prefixes_added': [], 'prefixes_removed': [], 'added_count': len(added),
                'removed_count': len(removed), 'changed_count': 0, 'prefixes_added_count': 0,
                'prefixes_removed_count': 0}

    def inject(route):
        data = route.fetch().json()
        if data.get('prefix') == '10.20.48.0/24':
            history = [record(1767225600, added=['10.20.48.1']),
                       record(1767139200, removed=['10.20.48.200', '10.20.48.201']),
                       record(1767052800, added=['10.20.48.5', '10.20.48.6', '10.20.48.7'])]
            data['changes'], data['changes_history'] = history[0], history
        route.fulfill(json=data)

    page = open_page(f'{BASE}/map/1/10_20_48_0_24', route=(f'**{BASE}/data/**', inject))
    wait_for_map(page)
    section = page.locator('#sum-free section:has-text("Last change")')
    rows = section.locator('table.history tr')
    assert rows.count() == 3 and 'current' in rows.nth(0).get_attribute('class')
    assert rows.nth(2).locator('td.n').inner_text() == '3 IP added'
    page.check('#show-changes')
    rows.nth(1).click()
    section = page.locator('#sum-free section:has-text("Earlier change")')
    assert section.locator('.sub').inner_text() == '2 removed'
    assert page.locator('#ov-changes .ov-change.removed').count() == 2
    assert page.locator('#ov-changes .ov-change.added').count() == 0
    assert page.errors == []
