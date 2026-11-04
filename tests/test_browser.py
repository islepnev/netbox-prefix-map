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
def test_zoom_is_whole_device_pixels(open_page, dpr):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20', device_scale_factor=dpr)
    wait_for_map(page)
    natural, css_width = page.eval_on_selector(
        '#map-img', 'img => [img.naturalWidth, img.getBoundingClientRect().width]')
    k = css_width * dpr / natural
    assert k == int(k) >= 1
    page.click('#zoom-in')
    assert page.eval_on_selector('#map-img', 'img => img.getBoundingClientRect().width') * dpr / natural == k + 1
    assert page.inner_text('#zoom-level') == f'{int(k) + 1}×'
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
    assert 'pinned' in page.inner_text('#search-msg')
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


@pytest.mark.parametrize("path", ['/', '/map/1', '/map/None', '/map/1/10_0_0_0_8', '/map/None/172_31_0_0_16',
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


def test_svg_export_black_and_white_hatches_tenants(open_page):
    page = open_page(f'{BASE}/map/1/10_20_0_0_17')
    wait_for_map(page)
    _, root = export_svg(page, mono=True)
    patterns = root.findall(f'.//{SVG_NS}pattern')
    assert len(patterns) >= 8
    fills = {r.get('fill') for r in root.iter(SVG_NS + 'rect') if r.find(SVG_NS + 'title') is not None}
    assert fills <= {f'url(#t{i})' for i in range(len(patterns))} | {'none'}


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
    assert 'assigned' in page.inner_text('#sum-usage')
