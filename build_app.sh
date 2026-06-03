#!/usr/bin/env bash
# build_app.sh — Build the complete Godavari Leads desktop app (Tauri + Python).
#
# IMPORTANT: Install the DMG output, NOT dist/GodavariLeads.app from PyInstaller alone.
# PyInstaller-only .app is missing Resources/leads-bin/ and will white-screen in Tauri.
#
# Usage:
#   ./scripts/kill_godavari_leads.sh   # if stuck / infinite windows
#   ./build_app.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

export PATH="$HOME/.cargo/bin:$HOME/Library/Python/3.9/bin:$PATH"

VERSION="1.1.0"
ARCH="$(uname -m)"
DMG_NAME="GodavariLeads_${VERSION}_${ARCH}.dmg"

die() { echo "ERROR: $*" >&2; exit 1; }

echo "▶ Step 0: Stop stale Godavari processes (free port 8000)..."
if [ -x "$SCRIPT_DIR/scripts/kill_godavari_leads.sh" ]; then
  "$SCRIPT_DIR/scripts/kill_godavari_leads.sh" || true
fi

echo ""
echo "▶ Step 1: Build Python bundle with PyInstaller (clean build)..."
command -v pyinstaller >/dev/null 2>&1 || die "pyinstaller not found — pip install pyinstaller"
chmod -R u+w build/ dist/ 2>/dev/null || true
rm -rf build/ dist/
pyinstaller -y leads.spec
[ -x "dist/leads/leads" ] || die "dist/leads/leads missing after PyInstaller"
echo "  ✓ Python bundle: dist/leads/"

echo ""
echo "▶ Step 2: Build Tauri shell..."
command -v cargo >/dev/null 2>&1 || die "cargo not found — install Rust"
rm -rf src-tauri/leads-bin
cp -r dist/leads src-tauri/leads-bin
( cd src-tauri && cargo tauri build )
echo "  ✓ Tauri compiled"

TAURI_APP=""
CARGO_TARGET="$(cd src-tauri && cargo metadata --no-deps --format-version 1 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['target_directory'])" 2>/dev/null || true)"
for candidate in \
    "${CARGO_TARGET}/release/bundle/macos/GodavariLeads.app" \
    "${CARGO_TARGET}/release/bundle/macos/Leads.app" \
    "src-tauri/target/release/bundle/macos/GodavariLeads.app" \
    "src-tauri/target/release/bundle/macos/Leads.app"
do
    if [ -n "$candidate" ] && [ -d "$candidate" ]; then
        TAURI_APP="$candidate"
        break
    fi
done

[ -n "$TAURI_APP" ] || die "Could not locate Tauri-built .app under target/release/bundle/macos/"

if [[ "$TAURI_APP" == *"/Leads.app" ]]; then
    RENAMED_APP="${TAURI_APP%/Leads.app}/GodavariLeads.app"
    rm -rf "$RENAMED_APP"
    mv "$TAURI_APP" "$RENAMED_APP"
    TAURI_APP="$RENAMED_APP"
    echo "  ✓ Renamed bundle to GodavariLeads.app"
fi
echo "  ✓ Tauri bundle: $TAURI_APP"

echo ""
echo "▶ Step 3: Inject Python bundle into Contents/Resources/leads-bin/..."
RESOURCES="$TAURI_APP/Contents/Resources"
BACKEND="$RESOURCES/leads-bin/leads"
rm -rf "$RESOURCES/leads-bin"
rsync -a --exclude='*.pyc' dist/leads/ "$RESOURCES/leads-bin/"
chmod +x "$BACKEND"
[ -x "$BACKEND" ] || die "Backend not executable at $BACKEND"
echo "  ✓ Injected $(du -sh "$RESOURCES/leads-bin" | awk '{print $1}')"

echo ""
echo "▶ Step 4: Smoke-test backend (localhost:8000)..."
"$SCRIPT_DIR/scripts/kill_godavari_leads.sh" || true
LEADS_NO_BROWSER=1 "$BACKEND" &
SMOKE_PID=$!
trap 'kill -9 "$SMOKE_PID" 2>/dev/null || true' EXIT
READY=0
for _ in $(seq 1 60); do
    if curl -sf -o /dev/null "http://127.0.0.1:8000/"; then
        READY=1
        break
    fi
    sleep 0.5
done
kill -9 "$SMOKE_PID" 2>/dev/null || true
wait "$SMOKE_PID" 2>/dev/null || true
trap - EXIT
[ "$READY" = 1 ] || die "Backend smoke test failed — check ~/Library/Application Support/GodavariLeads/leads.log"
echo "  ✓ Backend responds on http://127.0.0.1:8000/"

echo ""
echo "▶ Step 5: Package DMG..."
rm -f "$SCRIPT_DIR/$DMG_NAME"
RW_DMG="$SCRIPT_DIR/godavari_rw.dmg"
DMG_STAGING=$(mktemp -d)
trap 'rm -rf "$DMG_STAGING"' EXIT
cp -r "$TAURI_APP" "$DMG_STAGING/GodavariLeads.app"
codesign --force --deep --sign - "$DMG_STAGING/GodavariLeads.app" 2>&1 | head -2 || true
ln -sf /Applications "$DMG_STAGING/Applications"

if [ -f "$SCRIPT_DIR/src-tauri/assets/dmg-background.png" ]; then
  mkdir -p "$DMG_STAGING/.background"
  cp "$SCRIPT_DIR/src-tauri/assets/dmg-background.png" "$DMG_STAGING/.background/bg.png"
fi

rm -f "$RW_DMG"
hdiutil create -srcfolder "$DMG_STAGING" -volname "Godavari Leads" \
    -fs HFS+ -format UDRW -size 160m "$RW_DMG" >/dev/null
DEVICE=$(hdiutil attach -readwrite -noverify "$RW_DMG" 2>&1 | awk '/\/dev\// {print $1; exit}')
sleep 2
if [ -f "$DMG_STAGING/.background/bg.png" ]; then
  osascript <<'APPLESCRIPT' || true
tell application "Finder"
  tell disk "Godavari Leads"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set bounds of container window to {200, 120, 760, 440}
    set viewOptions to the icon view options of container window
    set arrangement of viewOptions to not arranged
    set icon size of viewOptions to 80
    set background picture of viewOptions to file ".background:bg.png"
    set position of item "GodavariLeads.app" to {140, 120}
    set position of item "Applications" to {420, 120}
    update without registering applications
    delay 2
    close
  end tell
end tell
APPLESCRIPT
fi
sync
hdiutil detach "$DEVICE" >/dev/null
hdiutil convert "$RW_DMG" -format UDZO -imagekey zlib-level=9 \
    -o "$SCRIPT_DIR/$DMG_NAME" >/dev/null
rm -f "$RW_DMG"

echo ""
echo "✅ Build complete"
echo "   Install from: $SCRIPT_DIR/$DMG_NAME"
echo "   App bundle:  $TAURI_APP"
du -sh "$SCRIPT_DIR/$DMG_NAME"
