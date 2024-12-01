# IP Address Allocation Visualization Script

## Overview

The **IP Address Allocation Visualization Script** generates a visual grid representation of IP address allocations based on input CSV files containing network prefixes and IP address details. The output is a PNG image that depicts allocated IPs, color-coded by tenant, roles, statuses, and tags, along with grid lines and prefix regions.

## Features

- **Grid Visualization**: Displays IP allocations on a configurable grid using a Z-order (Morton) curve.
- **Color Coding**: Differentiates IPs based on tenant assignments, roles, statuses, and tags.
- **Prefix Representation**: Highlights sub-prefixes within the top-level network prefix.
- **Flexible Configuration**: Supports square and rectangular grid dimensions with adjustable cell sizes.
- **Logging**: Provides detailed logging for monitoring and troubleshooting.

## Installation

### Prerequisites

- **Python 3.6+**
- **Required Python Libraries**:
  - `csv`
  - `ipaddress`
  - `math`
  - `matplotlib`
  - `numpy`
  - `logging`
  - `argparse`

### Installation Steps

1. **Clone the Repository**:

    ```bash
    git clone https://github.com/islepnev/ip-allocation-visualization.git
    cd ip-allocation-visualization
    ```

2. **Install Dependencies**:
    Ensure you have `pip` installed. Then, install the required libraries:

    ```bash
    pip install matplotlib numpy
    ```

## Usage

### Command-Line Arguments

- `-p`, `--prefixes`: Path to the prefixes CSV file.
  - **Default**: `prefixes.csv`
- `-i`, `--ip_addresses`: Path to the IP addresses CSV file.
  - **Default**: `ip_addresses.csv`
- `-o`, `--output`: Output PNG file name.
  - **Default**: `allocation_grid.png`
- `-c`, `--cell_size`: Size of each grid cell in pixels.
  - **Default**: `4`

### Running the Script

```bash
python ip_allocation_visualization.py -p path/to/prefixes.csv -i path/to/ip_addresses.csv -o output_image.png -c 5
```

### Example

```bash
python ip_allocation_visualization.py
```

This command uses the default file names and cell size:

- Prefixes CSV: `prefixes.csv`
- IP Addresses CSV: `ip_addresses.csv`
- Output PNG: `allocation_grid.png`
- Cell Size: `4` pixels

## Input Files

### Prefixes CSV

- **Purpose**: Define network prefixes and associated tenants.
- **Required Fields**:
  - `Prefix`: Network prefix (e.g., `192.168.0.0/16`)
  - `Tenant`: Associated tenant name
- **Additional Fields**: May include other arbitrary keys.

### IP Addresses CSV

- **Purpose**: Define IP address allocations and their attributes.
- **Required Fields**:
  - `IP Address`: Individual IP address (ignores any CIDR notation)
- **Optional Fields**:
  - `Tags`: Tags associated with the IP
  - `Role`: Role designation (e.g., `Router`, `Switch`)
  - `Status`: Allocation status (`Active`, `Reserved`, `Inactive`)
  - `Tenant`: Associated tenant name
- **Additional Fields**: May include other arbitrary keys.

## Output

- **Allocation Grid PNG Image**:
  - **Format**: PNG
  - **Content**: Visual grid showing allocated IPs, prefix regions, and grid lines with color coding based on tenants, roles, statuses, and tags.

## Grid Configuration

### Dimensions

- **Width (`GRID_WIDTH`)**: Integer power of 2 (e.g., 256)
- **Height (`GRID_HEIGHT`)**: Integer power of 2 (e.g., 128)
- **Supported Aspect Ratios**:
  - 1:1 (Square Grid): `GRID_WIDTH` == `GRID_HEIGHT`
  - 2:1 (Rectangular Grid): `GRID_WIDTH` == `2 * GRID_HEIGHT`

### Cell Size

- **Parameter**: `cell_size` (pixels)
- **Default**: 4 pixels
- **Characteristics**:
  - Cells are square.
  - Filled area: `cell_size - 1` pixels to maintain 1-pixel spacing.

## Color Mapping

### Tenant Color Mapping

- **Method**: Pre-built mapping from normalized tenant names to color hex codes using simple modulo division based on a predefined color palette.
- **Normalization**: Tenant names are converted to lowercase and stripped of non-alphanumeric characters.
- **Default Color**: `'none'` for unknown tenants.

### IP Color Determination

- **Conditions**:
  - If `Role` or `Tags` are non-empty: Assign a special color (e.g., deep red).
  - If `Status` is `Reserved`: Assign semi-transparent black (`alpha=0.25`).
  - If `Status` is `Inactive`: Assign transparent (`alpha=0`).
  - Otherwise: Assign default color (e.g., black).

## Logging

- **Levels**:
  - **INFO**: General operational messages (e.g., number of records loaded, progress updates).
  - **DEBUG**: Detailed diagnostic information (e.g., invalid IP formats, allocation counts).
- **Handlers**:
  - **Console**: Displays INFO level messages.
  - **File**: Logs DEBUG level messages to `ip_allocation.log`.

## Technical Components

- **Libraries**:
  - `csv`: For reading input CSV files.
  - `ipaddress`: For IP address manipulation.
  - `math`: For mathematical operations (e.g., log2).
  - `matplotlib`: For image generation.
  - `numpy`: For efficient grid data handling.
  - `logging`: For logging operations.
  - `argparse`: For command-line argument parsing.

## Constraints and Preconditions

- **Grid Dimensions**:
  - `GRID_WIDTH` and `GRID_HEIGHT` must be integer powers of 2.
  - Supported Aspect Ratios:
    - 1:1 (Square Grid)
    - 2:1 (Rectangular Grid: `GRID_WIDTH` == `2 * GRID_HEIGHT`)
- **Data Integrity**:
  - IP entries must contain a valid `IP Address` field.
  - Prefix entries must contain a valid `Prefix` field with a `/16` prefix length.
- **Color Palette**:
  - The predefined palette should cover the expected number of tenants to minimize color repetition.

## Extensibility

- **Grid Sizes**: Easily adjustable `GRID_WIDTH` and `GRID_HEIGHT` within supported aspect ratios.
- **Color Mapping**: Expand or modify the tenant color palette as needed.
- **Additional Features**: Potential to incorporate interactive elements or support for more complex prefix structures.

## Testing and Validation

- **Integration Tests**:
  - Ensure end-to-end functionality from CSV input to PNG output.
- **Visual Inspection**:
  - Verify the correctness of the generated PNG images, ensuring proper alignment, color coding, and absence of visual artifacts.
- **Edge Cases**:
  - Handle scenarios with missing fields, invalid IP addresses, or unsupported grid dimensions gracefully.

## License

[MIT License](LICENSE)
