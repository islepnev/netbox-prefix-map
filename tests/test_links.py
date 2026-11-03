import re
from collections import deque

BASE = '/prefix-map'
NETBOX = 'https://netbox.example.test'


def sanitize(prefix):
    return prefix.replace('.', '_').replace('/', '_')


def tree_links(data):
    """Links built by static/js/prefix_tree.js from a data file."""
    links = [f"{BASE}/map/{data.get('vrf') if data.get('vrf') is not None else 'None'}/{sanitize(data['prefix'])}"]
    for child in data.get('child_prefixes', []):
        vrf = child.get('vrf') if child.get('vrf') is not None else 'None'
        links.append(f"{BASE}/map/{vrf}/{sanitize(child['prefix'])}")
    return links


def crawl(client):
    queue, seen, broken, netbox_links = deque([f'{BASE}/']), set(), [], set()
    while queue:
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        r = client.get(url)
        if r.status_code != 200:
            broken.append((r.status_code, url))
            continue
        if not r.mimetype == 'text/html':
            continue
        links = re.findall(r'(?:href|src)="([^"]+)"', r.data.decode())
        match = re.match(rf'{BASE}/map/([^/]+)/(.+)$', url)
        if match:
            data = client.get(f'{BASE}/data/{match[1]}/{match[2]}').get_json()
            links += tree_links(data)
        for link in links:
            if link.startswith(NETBOX):
                netbox_links.add(link)
            elif link.startswith(BASE):
                queue.append(link)
    return seen, broken, netbox_links


def test_all_links_resolve(client):
    seen, broken, _ = crawl(client)
    assert len(seen) > 100
    assert broken == []


def test_netbox_links_have_ids(client):
    _, _, netbox_links = crawl(client)
    assert netbox_links
    bad = [link for link in netbox_links
           if re.search(r'/(None|undefined|null)?/$', link[len(NETBOX):]) and not link[len(NETBOX):] == '/']
    assert bad == []
    assert any('/tenancy/tenants/' in link for link in netbox_links)
    assert any('/ipam/roles/' in link for link in netbox_links)


def test_map_page_details(client, dataset):
    r = client.get(f'{BASE}/map/1/10_20_48_0_20').data.decode()
    assert 'Storage block' in r
    assert '>Storage</a>' in r
    assert 'Active' in r
    assert '>Access</a>' in r


def test_global_prefix_page(client, dataset):
    pid = next(p['id'] for p in dataset['prefixes'] if p['prefix'] == '172.31.4.0/24')
    r = client.get(f'{BASE}/map/None/172_31_4_0_24').data.decode()
    assert f'{NETBOX}/ipam/prefixes/{pid}/' in r
    assert 'Global subnet' in r and '>Core</a>' in r
    assert f'href="{BASE}/map/None"' in r, "breadcrumb to the Global VRF"
