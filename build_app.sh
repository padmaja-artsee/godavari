#!/usr/bin/env bash
# build_app.sh — Build the complete Godavari Leads desktop app
# Usage: ./build_app.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

export PATH="$HOME/.cargo/bin:$HOME/Library/Python/3.9/bin:$PATH"

echo "▶ Step 1: Build Python bundle with PyInstaller (clean build)..."
rm -rf build/ dist/
pyinstaller -y leads.spec
echo "  ✓ Python bundle built: dist/leads/"

echo ""
echo "▶ Step 2: Build Tauri Rust shell (no Python resources)..."
rm -rf src-tauri/leads-bin
cp -r dist/leads src-tauri/leads-bin
(cd src-tauri && cargo tauri build 2>&1 | grep -E "Compiling|Finished|Bundling|Error|error" | tail -6)
echo "  ✓ Tauri shell compiled"

# Locate the Tauri-built .app — check known cargo target locations first.
TAURI_APP=""
for candidate in \
    "$(cd src-tauri && cargo metadata --no-deps --format-version 1 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['target_directory'])" 2>/dev/null)/release/bundle/macos/Leads.app" \
    "/var/folders/mh/fqg3v7yn1y538bqtyl28_35r0000gn/T/cursor-sandbox-cache/699536e77528ae1fd82f92108e3cfa33/cargo-target/release/bundle/macos/Leads.app" \
    "src-tauri/target/release/bundle/macos/Leads.app"
do
    if [ -d "$candidate" ]; then
        TAURI_APP="$candidate"
        break
    fi
done

if [ -z "$TAURI_APP" ]; then
    echo "ERROR: Could not locate Tauri-built Leads.app" >&2
    exit 1
fi
echo "  ✓ Found bundle at: $TAURI_APP"

# Ensure the bundle is consistently named GodavariLeads.app (Tauri may produce
# Leads.app when it uses a cached binary from an older productName setting).
if [[ "$TAURI_APP" == *"/Leads.app" ]]; then
    RENAMED_APP="${TAURI_APP%/Leads.app}/GodavariLeads.app"
    rm -rf "$RENAMED_APP"
    mv "$TAURI_APP" "$RENAMED_APP"
    TAURI_APP="$RENAMED_APP"
    echo "  ✓ Renamed bundle to GodavariLeads.app"
fi

echo ""
echo "▶ Step 3: Inject Python bundle into app (preserving structure)..."
RESOURCES="$TAURI_APP/Contents/Resources"
rm -rf "$RESOURCES/leads-bin"
rsync -a --exclude='*.pyc' dist/leads/ "$RESOURCES/leads-bin/"
echo "  ✓ Python bundle injected"

echo ""
echo "▶ Step 4: Make Python binary executable..."
chmod +x "$RESOURCES/leads-bin/leads"
echo "  ✓ Permissions set"

echo ""
echo "▶ Step 5: Re-sign the bundle (ad-hoc, no developer certificate needed)..."
codesign --force --deep --sign - "$TAURI_APP" 2>&1 | head -5 || true
echo "  ✓ Signed (ad-hoc)"

echo ""
echo "▶ Step 6: Package into DMG..."
DMG_NAME="GodavariLeads_1.1.0_aarch64.dmg"
rm -f "$SCRIPT_DIR/$DMG_NAME"
hdiutil create \
    -volname "Godavari Leads" \
    -srcfolder "$TAURI_APP" \
    -ov -format UDZO \
    "$SCRIPT_DIR/$DMG_NAME" 2>&1 | tail -3
echo "  ✓ DMG created: $DMG_NAME"

echo ""
echo "✅ Build complete!"
echo "   App:  $TAURI_APP"
echo "   DMG:  $SCRIPT_DIR/$DMG_NAME"
du -sh "$SCRIPT_DIR/$DMG_NAME"
