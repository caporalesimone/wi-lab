#!/usr/bin/env bash
set -euo pipefail

# The script lives in scripts/; every path is resolved from the repository root.
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VERSION_FILE="$ROOT_DIR/VERSION"
PACKAGE_JSON="$ROOT_DIR/frontend/package.json"
PACKAGE_LOCK="$ROOT_DIR/frontend/package-lock.json"

usage() {
    cat <<'EOF'
Usage: ./scripts/update_version.sh [--bump-to X.Y.Z]

Options:
  --bump-to X.Y.Z   Set the next version non-interactively
  -h, --help        Show this help message

If --bump-to is not provided, the script prompts for the new version.
EOF
}

next=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bump-to)
            if [[ $# -lt 2 ]]; then
                echo "Error: --bump-to requires a version argument" >&2
                usage
                exit 1
            fi
            next="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Error: unknown argument '$1'" >&2
            usage
            exit 1
            ;;
    esac
done

# Read current version
current=$(cat "$VERSION_FILE" | tr -d '[:space:]')
echo "Current version: $current"

# Prompt for next version when not provided via CLI
if [[ -z "$next" ]]; then
    read -rp "Enter new version: " next
fi

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

# Update the package's own entries in package-lock.json (the top-level "version" and the
# one of packages[""]). Only the first lines are touched: a dependency further down can
# legitimately have the same version number.
sed -i "1,12s/\"version\": \"${current}\"/\"version\": \"${next}\"/" "$PACKAGE_LOCK"

version_file_value=$(tr -d '[:space:]' < "$VERSION_FILE")
frontend_version=$(sed -n 's/.*"version": "\([^"]*\)".*/\1/p' "$PACKAGE_JSON" | head -n 1)
lock_version=$(sed -n 's/.*"version": "\([^"]*\)".*/\1/p' "$PACKAGE_LOCK" | head -n 1)

echo ""
echo "Version updated: $current → $next"
echo "  - $VERSION_FILE"
echo "  - $PACKAGE_JSON"
echo "  - $PACKAGE_LOCK"
echo ""
echo "Aligned versions:"
echo "  VERSION: $version_file_value"
echo "  frontend/package.json: $frontend_version"
echo "  frontend/package-lock.json: $lock_version"
echo ""
echo "Remember to update CHANGELOG.md before committing!"
