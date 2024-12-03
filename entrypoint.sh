#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Run the CLI script to generate output data files
python -m app.cli

# Start the Flask application
python -m app.webapp
