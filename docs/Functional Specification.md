# Functional Specification for IP Address Allocation Visualization

## 1. Introduction

The IP Address Allocation Visualization application provides real-time, interactive visualizations of IP address allocations within a network. It integrates with NetBox, a network resource modeling tool, to fetch network data and responds to updates via webhooks. The application aims to assist network administrators in understanding and managing IP address space efficiently.

## 2. Purpose and Scope

### 2.1 Purpose

The purpose of this application is to visualize IP address allocations across the network in an interactive and user-friendly manner. It enables administrators to:

- View real-time allocation of IP addresses and prefixes.
- Navigate through different network segments and prefixes.
- Identify and analyze the utilization of IP address space.
- Receive updates and reflect changes promptly upon network modifications.

### 2.2 Scope

The application focuses on:

- Integration with NetBox via its API and webhooks.
- Generating visual representations of IP address allocations.
- Providing an interactive web interface for navigation and analysis.
- Ensuring consistent visualization across different network segments and VRFs (Virtual Routing and Forwarding instances).

## 3. User Expectations

Users of the application, primarily network administrators, expect:

- **Real-Time Updates**: The visualization reflects the latest state of the network, updating promptly after changes in NetBox.
- **Interactive Navigation**: Ability to drill down into specific prefixes, view details on hover, and navigate through the network hierarchy.
- **Consistent Visuals**: Stable color mapping for tenants and clear representations that remain consistent across sessions.
- **Ease of Access**: Accessible via a web interface without requiring authentication (for the initial version), with plans for future authentication mechanisms.
- **Diagnostic Tools**: Ability to view error logs and receive feedback on processing errors in a user-friendly format.

## 4. Functional Requirements

### 4.1 Integration with NetBox

- **API Integration**: Fetch prefixes, IP addresses, and related data from NetBox using its API.
- **Webhook Handling**: Receive and process webhook events from NetBox when prefixes or IP addresses are created, updated, or deleted.
- **Data Consistency**: Ensure that the visualization data is up-to-date with the current state of NetBox.

### 4.2 Visualization Generation

- **Recursive Prefix Traversal**: Traverse all prefixes, starting from top-level prefixes, and include their child prefixes in the visualization.
- **Dynamic Output Generation**: Generate visualization outputs (images and data files) for each prefix, stored in a configurable output directory.
- **Conditional Regeneration**: Regenerate visualization outputs only when relevant data has changed, optimizing performance and resource usage.
- **Tenant Color Mapping**: Map tenants to colors consistently across sessions, ensuring that each tenant is represented by the same color in all visualizations.

### 4.3 Interactive Web Interface

- **Visualization Display**: Serve the generated visualizations through a web interface, accessible via a web browser.
- **Interactive Features**:
  - **Hover Details**: Display IP address or prefix details when hovering over elements in the visualization.
  - **Drill-Down Navigation**: Allow users to double-click on prefixes to navigate deeper into the network hierarchy.
  - **Prefix Tree Navigation**: Provide a visual representation of the prefix hierarchy for easy navigation, highlighting the current prefix.

### 4.4 Error Reporting

- **Error Logs Access**: Provide a web interface to view recent error logs.
- **User-Friendly Presentation**: Display logs with color-coded severity levels and highlighted key-value pairs for readability.

### 4.5 Configuration and Customization

- **Output Directory Configuration**: Allow the output directory for generated files to be configurable via environment variables.
- **Time Zone Configuration**: Use a single time zone for timestamp handling, configurable via environment variables, defaulting to UTC.

## 5. Non-Functional Requirements

### 5.1 Performance

- **Efficient Processing**: Optimize data fetching and processing to handle updates promptly without significant delays.
- **Scalability**: Design the application to handle growth in network size and complexity.

### 5.2 Usability

- **User-Friendly Interface**: Provide an intuitive and responsive web interface that is easy to navigate.
- **Accessibility**: Ensure the application is accessible without requiring authentication for the initial version.

### 5.3 Maintainability

- **Modular Code Structure**: Organize code into modules for ease of maintenance and future enhancements.
- **Logging and Diagnostics**: Implement comprehensive logging to aid in troubleshooting and monitoring.

### 5.4 Security

- **Future Authentication Plans**: Plan for future integration with authentication mechanisms (e.g., OIDC) to restrict access as needed.
- **Secure Configuration Handling**: Store sensitive configuration data, such as API tokens, securely using environment variables.

## 6. Constraints and Assumptions

- The application will run in an environment where NetBox is accessible via its API and can send webhooks to the application.
- The network administrators using the application have a basic understanding of network concepts and NetBox.
- Performance considerations are secondary to functionality for the initial version, as the utility is for in-house use.

## 7. Future Enhancements

- **Authentication Integration**: Implement user authentication to control access to the application.
- **Advanced Analytics**: Provide more detailed analytics on IP address utilization and trends.
- **Customization Options**: Allow users to customize visualization settings, such as color schemes and display preferences.
