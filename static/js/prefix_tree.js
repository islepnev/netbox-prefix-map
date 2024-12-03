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

    // Fetch and render the prefix tree
    function fetchAndRenderTree(vrf, prefix, parentElement) {
        const sanitizedPrefix = sanitizePrefix(prefix);
        const treeUrl = `/data/${vrf ?? 'None'}/${sanitizedPrefix}`;

        fetch(treeUrl)
            .then(response => {
                if (!response.ok) {
                    throw new Error("Failed to fetch prefix tree data.");
                }
                return response.json();
            })
            .then(data => {
                parentElement.innerHTML = ""; // Clear the "Loading..." text
                renderTree(data, parentElement);
            })
            .catch(error => {
                console.error(error);
                parentElement.innerHTML = "Failed to load prefix tree.";
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
        link.href = `/map/${data.vrf ?? 'None'}/${sanitizedPrefix}`;
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
                        childLink.href = `/map/${child.vrf ?? 'None'}/${childSanitizedPrefix}`;
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
    const urlParts = currentUrl.split("/");
    const vrf = urlParts[2];
    const sanitizedPrefix = urlParts.slice(3).join("/");
    const prefix = reconstructPrefix(sanitizedPrefix);

    if (prefix) {
        prefixTreeContainer.innerHTML = "Loading..."; // Set initial "Loading..." text
        fetchAndRenderTree(vrf, prefix, prefixTreeContainer);
    } else {
        prefixTreeContainer.innerHTML = "No prefix specified.";
    }
});
