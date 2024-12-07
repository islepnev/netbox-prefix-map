# Functional Specification for NetBox Prefix Map

## 1. Introduction

The NetBox Prefix Map application provides real-time, interactive visualizations of IP address allocations within a network. It integrates closely with NetBox, a network source of truth, to fetch network data and respond promptly to updates triggered by webhooks. The application aims to help network administrators understand, manage, and navigate their IP address space effectively. All application routes and the web interface are served from a configurable base path (e.g., `/prefix-map`), allowing seamless coexistence with a NetBox instance on the same host.

## 2. Purpose and Scope

### 2.1 Purpose

The purpose of this application is to visualize IP address allocations across the network in an interactive, user-friendly manner. It enables administrators to:

- View real-time allocation of IP addresses and prefixes.
- Navigate through hierarchical prefix structures and VRFs.
- Identify and analyze IP address space utilization trends.
- Reflect changes promptly upon receiving updates from NetBox.

### 2.2 Scope

The application focuses on:

- Integrating with NetBox via its API and webhooks.
- Generating visual representations of IP address allocations.
- Providing an interactive web interface for analysis and navigation, accessible under a configurable subdirectory for compatibility with co-located NetBox installations.
- Ensuring consistent color mapping and stable visuals across different prefixes and VRFs.

## 3. User Expectations

Users, primarily network administrators, expect:

- **Real-Time Updates**: The visualization promptly reflects changes made in NetBox.
- **Interactive Navigation**: Ability to drill down into prefixes, hover to see details, and move through the prefix hierarchy seamlessly.
- **Consistent Visuals**: Stable and recognizable color schemes for tenants and roles, remaining consistent across sessions.
- **Easy Access**: The interface should be accessible via a web browser under the configured base path (e.g., `/prefix-map`) without initial authentication.
- **Diagnostic Tools**: An interface to view error logs and technical details for debugging and analysis.

## 4. Functional Requirements

### 4.1 Integration with NetBox

- **API Integration**: Fetch prefixes, IP addresses, and related data from NetBox using its API.
- **Webhook Handling**: Receive and process webhook events from NetBox whenever prefixes or IP addresses change.
- **Data Consistency**: Maintain up-to-date visualization data, ensuring that network changes are accurately represented.

### 4.2 Visualization Generation

- **Recursive Prefix Traversal**: Explore all prefixes starting from top-level prefixes, including their child prefixes.
- **Dynamic Output Generation**: Produce visualization outputs (images, data files) for each prefix, stored in a configurable output directory.
- **Conditional Regeneration**: Regenerate outputs only when data changes, optimizing resource usage.
- **Tenant Color Mapping**: Assign stable, consistent colors to tenants for recognizable and clear visual differentiation.

### 4.3 Interactive Web Interface

- **Visualization Display**: Provide a web interface (served from a configurable base path) to view the generated visualizations.
- **Interactive Features**:
  - **Hover Details**: Reveal IP or prefix details on hover.
  - **Drill-Down Navigation**: Double-click or interact with prefixes to navigate deeper into the hierarchy.
  - **Prefix Tree Navigation**: Display a hierarchical tree of prefixes for intuitive exploration, highlighting the current prefix.

### 4.4 Configuration and Customization

- **Output Directory Configuration**: Allow the output directory to be set via environment variables.
- **Base Path Configuration**: Serve the entire application under a configurable subdirectory (e.g., `/prefix-map`) set via environment variables, ensuring no conflicts with NetBox’s own URLs.

## 5. Non-Functional Requirements

### 5.1 Performance

- **Efficient Processing**: Optimize data fetching and rendering to handle updates rapidly.

### 5.2 Usability

- **User-Friendly Interface**: Offer an intuitive, responsive UI.
- **Accessibility**: Initially no authentication required, with a clear, easy-to-navigate interface.

### 5.3 Maintainability

- **Modular Code Structure**: Organize code into logical modules.
- **Logging and Diagnostics**: Implement comprehensive logging for debugging and operational monitoring.

### 5.4 Security

- **Future Authentication Plans**: Plan for future integration with authentication/authorization solutions (e.g., OIDC).
- **Secure Configuration Handling**: Store sensitive configuration details (e.g., API tokens) securely via environment variables.

## 6. Constraints and Assumptions

- The application is deployed alongside NetBox on the same host, requiring a distinct base path to avoid URL conflicts.
- Administrators are assumed to have basic network and NetBox knowledge.
- Performance is secondary to functionality in initial releases as it’s an internal utility.
