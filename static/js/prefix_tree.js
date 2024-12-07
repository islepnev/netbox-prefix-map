// static/js/prefix_tree.js

document.addEventListener("DOMContentLoaded", () => {

    const prefixTreeContainer = document.getElementById("prefix-tree");

    // Function to sanitize prefix for URL (replace '.' and '/' with '_')
    function sanitizePrefix(prefix) {
        return prefix.replace(/\./g, '_').replace(/\//g, '_');
    }

    // Function to reconstruct prefix from sanitized version
    function reconstructPrefix(sanitized) {
        const parts = sanitized.split('_');
        if (parts.length >= 5) {
            const prefix_length = parts.pop();
            const ip_address = parts.join('.');
            return `${ip_address}/${prefix_length}`;
        } else {
            return sanitized.replace(/_/g, '.');
        }
    }

    // Show a spinner as the busy indicator
    function showBusyIndicator(parentElement) {
        const spinner = document.createElement("div");
        spinner.className = "spinner";
        spinner.innerHTML = `
            <div class="spinner-ring"></div>
            <p>Loading...</p>
        `;
        parentElement.innerHTML = ""; // Clear any existing content
        parentElement.appendChild(spinner);
    }

    // Remove the busy indicator
    function removeBusyIndicator(parentElement) {
        parentElement.innerHTML = ""; // Clear spinner and loading text
    }

    // Fetch and render the prefix tree
    function fetchAndRenderTree(vrf, prefix, parentElement) {
        const sanitizedPrefix = sanitizePrefix(prefix);
        const treeUrl = `${BASE_PATH}/data/${vrf ?? 'None'}/${sanitizedPrefix}`;

        showBusyIndicator(parentElement);

        fetch(treeUrl)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Failed to fetch prefix tree data from URL: ${treeUrl}`);
                }
                return response.json();
            })
            .then(data => {
                removeBusyIndicator(parentElement);
                renderTree(data, parentElement);
            })
            .catch(error => {
                console.error(error);
                removeBusyIndicator(parentElement);
                parentElement.innerHTML = `Failed to load prefix tree. URL: ${treeUrl}`;
            });
    }

    // Render the prefix tree as a nested list
    function renderTree(data, parentElement) {
        const ul = document.createElement("ul");

        // Create list item for the current prefix
        const li = document.createElement("li");
        const link = document.createElement("a");
        const displayPrefix = data.prefix;
        const sanitizedPrefix = sanitizePrefix(displayPrefix);
        link.href = `${BASE_PATH}/map/${data.vrf ?? 'None'}/${sanitizedPrefix}`;
        link.textContent = displayPrefix;
        li.appendChild(link);

        // If there are child prefixes, add a toggle button
        if (data.child_prefixes && data.child_prefixes.length > 0) {
            const toggleButton = document.createElement("button");
            toggleButton.textContent = " [+]";
            toggleButton.style.marginLeft = "10px";
            toggleButton.addEventListener("click", () => {
                if (toggleButton.textContent === " [+]") {
                    toggleButton.textContent = " [-]";
                    const childUl = document.createElement("ul");
                    data.child_prefixes.forEach(child => {
                        const childLi = document.createElement("li");
                        const childLink = document.createElement("a");
                        const childDisplayPrefix = child.prefix;
                        const childSanitizedPrefix = sanitizePrefix(childDisplayPrefix);
                        childLink.href = `${BASE_PATH}/map/${child.vrf ?? 'None'}/${childSanitizedPrefix}`;
                        childLink.textContent = childDisplayPrefix;
                        childLi.appendChild(childLink);
                        childUl.appendChild(childLi);

                        // Recursively fetch and render children
                        const childVrf = child.vrf ?? 'None';
                        fetchAndRenderTree(childVrf, childDisplayPrefix, childLi);
                    });
                    li.appendChild(childUl);
                } else {
                    toggleButton.textContent = " [+]";
                    const childUl = li.querySelector("ul");
                    if (childUl) {
                        li.removeChild(childUl);
                    }
                }
            });
            li.appendChild(toggleButton);
        }

        ul.appendChild(li);
        parentElement.appendChild(ul);
    }

    // Extract VRF and prefix from the current URL
    const currentUrl = window.location.pathname;
    const urlParts = currentUrl.replace(BASE_PATH, "").split("/");
    const vrf = urlParts[2] ?? 'None';  // Correctly extract VRF
    const sanitizedPrefix = urlParts.slice(3).join("/");
    const prefix = sanitizedPrefix ? reconstructPrefix(sanitizedPrefix) : null;

    if (prefix) {
        showBusyIndicator(prefixTreeContainer);
        fetchAndRenderTree(vrf, prefix, prefixTreeContainer);
    } else {
        prefixTreeContainer.innerHTML = "No prefix specified.";
    }
});
