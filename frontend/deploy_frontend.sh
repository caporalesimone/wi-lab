#!/bin/bash
set -e

# Wi-Lab Frontend Build Script (Docker-based)
# This script builds a minified production-ready Angular frontend bundle using Docker.
# Output: ./dist/wi-lab-frontend/
# No local dependencies required (Node.js, npm, etc.)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}"
IMAGE_NAME="wi-lab-frontend:build"
CONTAINER_NAME="wi-lab-frontend-build-$$"
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"

echo "=== Wi-Lab Frontend Build (Docker) ==="
echo ""

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed or not in PATH"
    echo "Please install Docker to build the frontend"
    exit 1
fi

echo "✓ Docker found"
echo ""

# Clean up old build output (optional)
echo "🧹 Preparing build directory..."
rm -rf "${PROJECT_ROOT}/dist"
mkdir -p "${PROJECT_ROOT}/dist"

# Build Docker image
echo "🔨 Building Docker image: ${IMAGE_NAME}"
docker build -t "${IMAGE_NAME}" "${PROJECT_ROOT}"
echo "✓ Docker image built"
echo ""

# Run container and extract build artifacts from image to local dist
echo "📦 Compiling Angular application (production mode) and copying artifacts..."
docker run --rm \
    --name "${CONTAINER_NAME}" \
    -v "${PROJECT_ROOT}/dist:/out" \
    "${IMAGE_NAME}" \
    sh -c "cp -r /build-output/wi-lab-frontend /out/ && chown -R ${HOST_UID}:${HOST_GID} /out/wi-lab-frontend"

BUILD_OUTPUT="${PROJECT_ROOT}/dist/wi-lab-frontend"

# Verify build output
if [ -d "${BUILD_OUTPUT}" ]; then
    echo ""
    echo "✅ Build successful!"
    echo ""
    echo "Output directory: ${BUILD_OUTPUT}"
    echo ""
    echo "Build artifacts:"
    ls -lh "${BUILD_OUTPUT}"/ | grep -v "^total" | awk '{print "  " $9 " (" $5 ")"}'
    echo ""
    echo "Total size:"
    du -sh "${BUILD_OUTPUT}" | awk '{print "  " $1}'
    echo ""
    echo "You can now copy the contents of ${BUILD_OUTPUT}"
    echo "to your desired location."
else
    echo "❌ Build failed: output directory not found"
    exit 1
fi
