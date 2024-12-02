// static/js/script.js

document.addEventListener('DOMContentLoaded', function() {
    // Get references to DOM elements
    const overlay = d3.select('#overlay');
    const tooltip = d3.select('#tooltip');
    const image = document.getElementById('visualization-image');

    // Set the SVG overlay dimensions to match the image dimensions
    overlay.attr('width', imageWidth).attr('height', imageHeight);

    // Fetch the data
    d3.json(dataUrl).then(function(data) {
        // Assume data contains 'ip_details' and 'prefix_rectangles'
        const ipDetails = data.ip_addresses;  // Adjusted based on data structure
        const prefixRectangles = data.child_prefixes;  // Adjusted based on data structure

        // Process and render IP addresses
        overlay.selectAll('rect.ip')
            .data(ipDetails)
            .enter()
            .append('rect')
            .attr('class', 'ip')
            .attr('x', d => d.x)
            .attr('y', d => d.y)
            .attr('width', d => d.width)
            .attr('height', d => d.height)
            .attr('fill', 'transparent')
            .on('mouseover', function(event, d) {
                tooltip.style('display', 'block')
                    .style('left', (event.pageX + 10) + 'px')
                    .style('top', (event.pageY + 10) + 'px')
                    .html(`IP Address: ${d.address}<br>Tenant: ${d.tenant || 'Unknown'}`);
            })
            .on('mouseout', function() {
                tooltip.style('display', 'none');
            });

        // Process and render prefixes
        overlay.selectAll('rect.prefix')
            .data(prefixRectangles)
            .enter()
            .append('rect')
            .attr('class', 'prefix')
            .attr('x', d => d.x)
            .attr('y', d => d.y)
            .attr('width', d => d.width)
            .attr('height', d => d.height)
            .attr('fill', 'transparent')
            .on('mouseover', function(event, d) {
                tooltip.style('display', 'block')
                    .style('left', (event.pageX + 10) + 'px')
                    .style('top', (event.pageY + 10) + 'px')
                    .html(`Prefix: ${d.prefix}<br>Tenant: ${d.tenant || 'Unknown'}`);
            })
            .on('mouseout', function() {
                tooltip.style('display', 'none');
            });
    }).catch(function(error) {
        console.error('Error fetching data:', error);
    });
});
