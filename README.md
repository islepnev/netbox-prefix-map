# NetBox Prefix Map Application

## Overview

The NetBox Prefix Map application fetches network data from NetBox and generates visual grid representations of IP address allocations. It integrates with NetBox via its API and processes webhook events for real-time updates.

## Features

- ✔️ **Grid Visualization**: Displays IP address allocations using a Z-order (Morton) curve.
- ✔️ **Dynamic Data Integration**: Fetches data from NetBox and updates visualizations on webhook events.
- ⚠️ **Interactive Web Interface**: Basic functionality implemented; further enhancements needed for drill-down navigation and prefix tree.
- ✔️ **Color Coding**: Differentiates IPs based on tenant assignments, roles, statuses, and tags.
- 🔧 **Logging and Error Reporting**: Logs errors and provides an interface for review.

## Installation

### Prerequisites

- Python 3.9+
- Valid NetBox API URL and token with read access to IPAM (IP address, prefix, VRF) and Tenancy (tenant)

### Installation Steps

1. Clone the Repository:

    ```bash
    git clone https://github.com/islepnev/netbox-prefix-map.git
    cd netbox-prefix-map
    ```

2. Install Dependencies:

    ```bash
    pip install -r requirements.txt
    ```

3. Configure Environment Variables:
   - `NETBOX_API_URL`: NetBox API URL.
   - `NETBOX_API_TOKEN`: Authentication token.
   - `OUTPUT_DIR`: Output directory for generated files (default: `output`).
   - `BASE_PATH`: Base path for serving the application (default: `/prefix-map`).

4. Run the CLI Script:

    ```bash
    python -m app.cli
    ```

5. Start the Flask Application:

    ```bash
    python -m app.webapp
    ```

## Running with Docker

1. Build the Docker Image:

    ```bash
    docker-compose build
    ```

2. Start the Application:

    ```bash
    docker-compose up
    ```

The application will be available at `http://localhost:5000/prefix-map`.

## Integrating with Apache Reverse Proxy

1. Enable the necessary Apache modules:

    ```bash
    sudo a2enmod proxy proxy_http rewrite
    sudo systemctl restart apache2
    ```

2. Add the following configuration to your Apache virtual host file for the NetBox site:

    ```apache
    <Location /prefix-map>
        ProxyPass http://localhost:5000/prefix-map
        ProxyPassReverse http://localhost:5000/prefix-map
    </Location>
    ```

3. Reload Apache:

    ```bash
    sudo systemctl reload apache2
    ```

The application will be available under the `/prefix-map` path of your NetBox site.

## Data Processing and Visualization

- ✔️ **Data Fetching**: Retrieves prefix and IP data from NetBox
- ✔️ **Recursive Prefix Traversal**: Identifies hierarchical relationships in prefixes
- ✔️ **Image Generation**: Generates PNG visualizations with `matplotlib`
- ✔️ **Color Mapping**: Assigns stable colors to tenants for consistent visuals

## Webhook Integration

- Expects NetBox to send webhook events for prefixes and IP addresses to the `/webhook` endpoint
- Processes events to update visualizations dynamically

## Constraints and Assumptions

- The application assumes deployment alongside NetBox on the same host, with a distinct base path to avoid URL conflicts
- WSGI not supported yet
