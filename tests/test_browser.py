import os
import socket
import threading

import pytest

from app.plot_map import decode_offset, get_max_bits
from tests.conftest import CELL_SIZE

playwright_api = pytest.importorskip("playwright.sync_api")

BASE = '/prefix-map'


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

    def _open(path, device_scale_factor=1):
        ctx = browser.new_context(viewport={'width': 1400, 'height': 900}, device_scale_factor=device_scale_factor)
        contexts.append(ctx)
        page = ctx.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and 'Failed to load resource' not in m.text
                and page.errors.append(m.text))
        page.on('response', lambda r: r.status >= 400 and page.errors.append(f'{r.status} {r.url}'))
        page.goto(server + path)
        return page

    yield _open
    for ctx in contexts:
        ctx.close()


def wait_for_map(page):
    page.wait_for_function("document.getElementById('map-usage').textContent.length > 0")


def cell_center(page, x, y):
    box = page.eval_on_selector('#map-image', '''img => {
        const r = img.getBoundingClientRect();
        return {left: r.left, top: r.top, k: r.width / img.naturalWidth};
    }''')
    cs = CELL_SIZE
    return box['left'] + (x * cs + cs / 2) * box['k'], box['top'] + (y * cs + cs / 2) * box['k']


@pytest.mark.parametrize("dpr", [1, 2])
def test_zoom_is_whole_device_pixels(open_page, dpr):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20', device_scale_factor=dpr)
    wait_for_map(page)
    natural, css_width = page.eval_on_selector(
        '#map-image', 'img => [img.naturalWidth, img.getBoundingClientRect().width]')
    device_px_per_image_px = css_width * dpr / natural
    assert device_px_per_image_px == int(device_px_per_image_px) >= 1
    page.click('#zoom-in')
    assert page.eval_on_selector('#map-image', 'img => img.getBoundingClientRect().width') * dpr / natural == \
        device_px_per_image_px + 1
    assert page.errors == []


def test_hover_shows_ip_and_prefix(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20')
    wait_for_map(page)
    page.mouse.move(*cell_center(page, 1, 0))  # 10.20.48.1
    text = page.inner_text('#map-tooltip')
    assert '10.20.48.1' in text and 'anycast' in text and 'gw-48.example.test' in text
    assert '10.20.48.0/24: Storage' in text
    assert 'Click: open 10.20.48.0/24' in text
    assert page.is_visible('#hover-cell')
    assert page.errors == []


def test_free_cell_tooltip(open_page, dataset):
    used = {ip['address'].split('/')[0] for ip in dataset['ip_addresses']}
    free = next(f"10.20.48.{host}" for host in range(2, 255) if f"10.20.48.{host}" not in used)
    x, y = decode_offset(int(free.split('.')[-1]), get_max_bits(64, 64), 64, 64)
    page = open_page(f'{BASE}/map/1/10_20_48_0_20')
    wait_for_map(page)
    page.mouse.move(*cell_center(page, x, y))
    assert page.inner_text('#map-tooltip .tt-title').split() == [free, 'free']


def test_click_drills_down(open_page):
    page = open_page(f'{BASE}/map/1/10_20_48_0_20')
    wait_for_map(page)
    with page.expect_navigation():
        page.mouse.click(*cell_center(page, 1, 0))
    assert page.url.endswith(f'{BASE}/map/1/10_20_48_0_24')


def test_tree_expands_lazily_and_links_resolve(open_page, server):
    page = open_page(f'{BASE}/map/1/10_20_0_0_17')
    page.wait_for_selector('#prefix-tree li li')
    requests = []
    page.on('request', lambda r: requests.append(r.url))
    page.locator('#prefix-tree li li .tree-toggle').first.click()
    page.wait_for_selector('#prefix-tree li li li')
    assert all(url.endswith('?nav=1') for url in requests if '/data/' in url)
    links = page.eval_on_selector_all('#prefix-tree a', 'els => els.map(e => e.getAttribute("href"))')
    assert len(links) > 10
    for link in links:
        assert page.request.get(server + link).status == 200, link
    assert page.errors == []


@pytest.mark.parametrize("path", ['/', '/map/1', '/map/None', '/map/1/10_0_0_0_8', '/map/None/172_31_0_0_16'])
def test_pages_have_no_script_errors(open_page, path):
    page = open_page(BASE + path)
    page.wait_for_load_state('networkidle')
    assert page.errors == []
