// static/js/prefix_tree.js

document.addEventListener("DOMContentLoaded", () => {
    const prefixTreeContainer = document.getElementById("prefix-tree");

    // Fetch and render the prefix tree
    function fetchAndRenderTree(vrf, prefix, parentElement) {
        const sanitizedPrefix = prefix.replace(/\./g, '_').replace(/\//g, '_');
        const treeUrl = `/data/${vrf ?? 'None'}/${sanitizedPrefix}`;

        fetch(treeUrl)
            .then(response => {
                if (!response.ok) {
                    throw new Error("Failed to fetch prefix tree data.");
                }
                return response.json();
            })
            .then(data => {
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
        link.href = `/map/${data.vrf ?? 'None'}/${data.prefix.replace(/\./g, '_').replace(/\//g, '_')}`;
        link.textContent = data.prefix;
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
                        childLink.href = `/map/${child.vrf ?? 'None'}/${child.prefix.replace(/\./g, '_').replace(/\//g, '_')}`;
                        childLink.textContent = child.prefix;
                        childLi.appendChild(childLink);
                        childUl.appendChild(childLi);

                        // Recursively fetch and render children
                        const childVrf = child.vrf ?? 'None';
                        fetchAndRenderTree(childVrf, child.prefix, childLi);
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
    const prefix = urlParts.slice(3).join("/").replace(/_/g, ".");

    if (prefix) {
        fetchAndRenderTree(vrf, prefix, prefixTreeContainer);
    } else {
        prefixTreeContainer.innerHTML = "No prefix specified.";
    }
});
