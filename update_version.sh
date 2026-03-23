#!/usr/bin/env bash
set -euo pipefail

VERSION_FILE="$(dirname "$0")/VERSION"
PACKAGE_JSON="$(dirname "$0")/frontend/package.json"

# Read current version
current=$(cat "$VERSION_FILE" | tr -d '[:space:]')
echo "Current version: $current"

# Prompt for next version
read -rp "Enter new version: " next

# Validate format a.b.c
if ! [[ "$next" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: '$next' is not a valid semantic version (expected format: a.b.c)" >&2
    exit 1
fi

# Compare versions: split into components
IFS='.' read -r cur_major cur_minor cur_patch <<< "$current"
IFS='.' read -r new_major new_minor new_patch <<< "$next"

is_greater=false
if   (( new_major > cur_major )); then
    is_greater=true
elif (( new_major == cur_major && new_minor > cur_minor )); then
    is_greater=true
elif (( new_major == cur_major && new_minor == cur_minor && new_patch > cur_patch )); then
    is_greater=true
fi

if ! $is_greater; then
    echo "Error: new version '$next' must be greater than current version '$current'" >&2
    exit 1
fi

# Update VERSION
echo "$next" > "$VERSION_FILE"

# Update version in frontend/package.json
sed -i "s/\"version\": \"${current}\"/\"version\": \"${next}\"/" "$PACKAGE_JSON"

echo ""
echo "Version updated: $current → $next"
echo "  - $VERSION_FILE"
echo "  - $PACKAGE_JSON"
echo ""
echo "Remember to update CHANGELOG.md before committing!"
