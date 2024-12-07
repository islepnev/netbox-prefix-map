# Technical Specification for IP Address Allocation Visualization

## 1. Overview

This document outlines the technical implementation details of the IP Address Allocation Visualization application. It describes the system architecture, components, and the interactions between them to fulfill the functional requirements specified.

## 2. System Architecture

The application consists of the following primary components:

- **Data Fetching Module**: Handles communication with the NetBox API to retrieve prefixes, IP addresses, and related data.
- **Data Processing Module**: Processes fetched data, including recursive traversal of prefixes, filtering of relevant IP addresses, and preparation for visualization.
- **Visualization Generation Module**: Generates visual representations of IP address allocations, including images and data files.
- **Web Server Module (Flask App)**: Serves the web interface, handles webhook events, and provides endpoints for interactive features and error reporting.
- **Utility Module**: Contains shared utility functions, such as data sanitization and tenant color mapping.

## 3. Components and Interactions

### 3.1 Data Fetching Module

- **NetBox API Integration**:
  - Utilizes the `pynetbox` library to interact with the NetBox API.
  - Fetches all prefixes and IP addresses, including their attributes such as VRF, tenant, status, and last updated timestamps.
- **Configuration**:
  - API URL and token are read from environment variables for security.
  - Supports configuration via a `.env` file.

### 3.2 Data Processing Module

- **Recursive Prefix Traversal**:
  - Processes each top-level prefix and collects all its child prefixes using subnet relationships.
  - Filters IP addresses to include only those relevant to each prefix.
- **Data Storage**:
  - Saves processed data for each prefix as JSON files in the configurable output directory.
  - Compares current data with existing data to determine if regeneration is necessary.

### 3.3 Visualization Generation Module

- **Image Generation**:
  - Uses `matplotlib` to create visual representations of IP address allocations.
  - Implements a grid-based visualization where each cell represents an IP address.
- **Tenant Color Mapping**:
  - Maps tenants to colors consistently by sorting tenant names and assigning colors from a predefined palette.
  - Ensures stable color representation across sessions.
- **Handling of Child Prefixes**:
  - Calculates rectangles representing child prefixes within the top-level prefix for hierarchical visualization.
- **Output Management**:
  - Generates output files (images and data files) using a naming convention that includes sanitized VRF and prefix names.
  - Stores outputs in the configurable output directory.

### 3.4 Web Server Module (Flask App)

- **Webhook Handling**:
  - Defines an endpoint to receive webhook events from NetBox.
  - Parses webhook data to identify affected prefixes and triggers data regeneration when necessary.
- **Serving Visualizations**:
  - Provides routes to serve generated images and data files.
  - Renders HTML templates that incorporate interactive features using JavaScript libraries.
- **Interactive Features**:
  - Implements hover details and drill-down navigation using D3.js or a similar JavaScript library.
  - Provides a prefix tree navigation component for hierarchical exploration.

### 3.5 Utility Module

- **Data Sanitization**:
  - Implements functions to sanitize VRF and prefix names for use in filenames by replacing non-alphanumeric characters with underscores.
- **Time Zone Handling**:
  - Manages time zone configurations using environment variables, defaulting to UTC.
  - Ensures consistent timestamp handling when comparing data modification times.
- **Helper Functions**:
  - Includes functions for determining if a prefix is a child of another and if an IP address is within a given prefix.

## 4. API Integrations

### 4.1 NetBox API

- **Authentication**:
  - Uses API tokens provided via environment variables.
- **Endpoints Used**:
  - **Prefixes**: Retrieves all prefixes and their attributes.
  - **IP Addresses**: Retrieves all IP addresses and their attributes.
- **Data Handling**:
  - Processes the data into a format suitable for visualization and storage.

### 4.2 Webhook Integration

- **Event Handling**:
  - Listens for webhook events related to prefixes and IP addresses (created, updated, deleted).
- **Processing Logic**:
  - Parses webhook payloads to determine which prefixes are affected.
  - Triggers data processing and visualization regeneration for affected prefixes.

## 5. Configuration and Deployment

### 5.1 Environment Variables

- **NETBOX_API_URL**: URL of the NetBox API.
- **NETBOX_API_TOKEN**: Authentication token for the NetBox API.
- **OUTPUT_DIR**: Directory where output files are stored, defaulting to `output`.

### 5.2 Deployment Considerations

- **Server Requirements**:
  - Python environment with necessary dependencies installed (`pynetbox`, `Flask`, `matplotlib`, etc.).
- **Running the Application**:
  - The Flask app runs as a web server, listening for incoming webhook events and serving the web interface.
- **Security**:
  - Sensitive configurations are stored securely using environment variables.

## 6. Error Handling and Logging

- **Logging Mechanisms**:
  - Logs are written to console.

## 7. Technology Stack

- **Programming Language**: Python
- **Frameworks and Libraries**:
  - **Flask**: For the web server and routing.
  - **pynetbox**: For interacting with the NetBox API.
  - **matplotlib**: For generating visualizations.
  - **D3.js** (or similar): For implementing interactive features on the web interface.
- **Data Formats**:
  - JSON: For storing processed data and configuration where applicable.
