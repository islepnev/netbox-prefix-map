// static/js/script.js

function initializeVisualization(data) {
    // Example: Highlight IP addresses on hover
    // This is a placeholder. You need to implement based on your visualization structure.

    // Assuming the image has an overlay with clickable areas or similar
    // For demonstration, adding hover effects to the image

    const img = d3.select("img")
        .on("mouseover", function(event) {
            // Show tooltip
            d3.select("#tooltip")
                .style("left", (event.pageX + 10) + "px")
                .style("top", (event.pageY + 10) + "px")
                .html("IP Details Here")  // Replace with actual data
                .classed("hidden", false);
        })
        .on("mousemove", function(event) {
            // Move tooltip with cursor
            d3.select("#tooltip")
                .style("left", (event.pageX + 10) + "px")
                .style("top", (event.pageY + 10) + "px");
        })
        .on("mouseout", function() {
            // Hide tooltip
            d3.select("#tooltip")
                .classed("hidden", true);
        })
        .on("dblclick", function(event) {
            // Implement drill-down navigation
            // Example: Redirect to a deeper prefix
            // window.location.href = `/map/${vrf}/${new_prefix}`;
        });
}
