import json, glob, os, shutil, sys
"""Build mockup.html from a synthetic full update.

Usage: python docs/mockup/build.py <output_dir> <dest_dir>
  output_dir: OUTPUT_DIR of full_update(mgr=FakeNetboxManager())
"""
O, M = sys.argv[1], sys.argv[2]
B = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(O + '/data-1-10_20_0_0_17.json'))
for k in ('render_hash',):
    data.pop(k, None)
for ip in data['ip_addresses']:
    ip.pop('vrf', None)
names = json.load(open(O + '/names.json'))
vrfs = json.load(open(O + '/vrf.json'))
tree = json.load(open(O + '/prefix_tree.json'))['1']['prefixes']
tenant_colors = {}
used = {}
for f in glob.glob(O + '/data-1-*.json'):
    d = json.load(open(f))
    used[d['prefix']] = len(d.get('ip_addresses', []))
    for p in d.get('nested_prefixes', []):
        if p.get('tenant') and p.get('color'):
            tenant_colors.setdefault(str(p['tenant']), p['color'])
nodes = [{'id': p['id'], 'prefix': p['prefix'], 'tenant': p['tenant'], 'status': p['status'],
          'description': p['description'], 'used': used.get(p['prefix']),
          'rendered': os.path.exists(f"{O}/address_map-1-{p['sanitized']}.png")} for p in tree if ':' not in p['prefix']]
payload = {'data': data, 'names': names, 'vrf': vrfs[0], 'tree': nodes, 'tenantColors': tenant_colors,
           'netbox': 'https://netbox.example'}
js = json.dumps(payload, separators=(',', ':')).replace('</', '<\\/')
src = open(B + '/mockup.src.html').read()
assert '__PAYLOAD__' in src
open(M + '/mockup.html', 'w').write(src.replace('__PAYLOAD__', js))
shutil.copy(O + '/address_map-1-10_20_0_0_17.png', M + '/address_map-1-10_20_0_0_17.png')
print('ok', len(js))
