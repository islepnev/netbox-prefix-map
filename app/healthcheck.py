"""Container healthcheck: exit 0 when the local web app answers /healthz."""

import os
import sys
import urllib.request


def main():
    port = os.getenv('PORT', '5000')
    base_path = os.getenv('BASE_PATH', '/prefix-map').rstrip('/')
    url = f"http://127.0.0.1:{port}{base_path}/healthz"
    # Bypass HTTP(S)_PROXY from the environment: the check must go direct
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=4) as response:
            return 0 if response.status == 200 else 1
    except Exception as e:
        print(f"healthcheck failed: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
