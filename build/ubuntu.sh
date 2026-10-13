#!/usr/bin/env bash
# Build the Ubuntu package: dist/release/pivot-benchmark_<version>_amd64.deb
# Run on an Ubuntu 22.04/24.04 machine from the repository root, inside the project venv:
#   bash build/ubuntu.sh
# Steps: PyInstaller bundle (build/pivot_benchmark.spec) -> /opt/pivot-benchmark layout ->
# launcher in /usr/bin, menu entry, Debian control file -> dpkg-deb.
# llama.cpp is NOT included; the app explains to the user how to get it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
VERSION=$(python -c "from mbench.version import VERSION; print(VERSION)")
DEBVER=${VERSION//-/\~}           # Debian: 0.9.0~preview sorts before 0.9.0
PKG=pivot-benchmark
STAGE="$ROOT/build/deb/$PKG"
OUT="${PKG}_${VERSION}_amd64.deb"      # file name keeps the dash: GitHub rewrites "~" in asset names
echo "== Pivot Benchmark $VERSION -> $OUT"

pip install -q pyinstaller
rm -rf build/pyi dist/PivotBenchmark "$STAGE"
pyinstaller --noconfirm --workpath build/pyi --distpath dist build/pivot_benchmark.spec >/dev/null
test -x dist/PivotBenchmark/PivotBenchmark

mkdir -p "$STAGE/DEBIAN" "$STAGE/opt/$PKG" "$STAGE/usr/bin" "$STAGE/usr/share/applications" "$STAGE/usr/share/doc/$PKG"
cp -r dist/PivotBenchmark/. "$STAGE/opt/$PKG/"
cat > "$STAGE/usr/bin/$PKG" <<EOF
#!/bin/sh
exec /opt/$PKG/PivotBenchmark "\$@"
EOF
chmod 755 "$STAGE/usr/bin/$PKG"
cat > "$STAGE/usr/share/applications/$PKG.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Pivot Benchmark
Comment=Find where an AI model breaks under social pressure
Exec=/usr/bin/$PKG
Terminal=false
Categories=Science;Development;
EOF
cat > "$STAGE/usr/share/doc/$PKG/README" <<EOF
Pivot Benchmark $VERSION (Ubuntu)
Start it from the applications menu or with: pivot-benchmark
Settings and results: ~/.local/share/pivot-benchmark
A local model needs llama.cpp on this computer (the Run tab explains); Gemini as adversary needs your own key (Settings).
Preview: the automatic classifier is under review; numbers may change in 1.0.
Licence: GPL-3.0-or-later (see /usr/share/doc/pivot-benchmark/LICENSE.md and NOTICE).
Downloads and checksums: https://github.com/zeravatechnologies/releases
Documentation: https://www.zeravatech.ca/products/pivot-benchmark/
EOF
if [ -f LICENSE.md ]; then cp LICENSE.md "$STAGE/usr/share/doc/$PKG/LICENSE.md"; fi
if [ -f NOTICE ]; then cp NOTICE "$STAGE/usr/share/doc/$PKG/NOTICE"; fi
pip install -q pip-licenses && pip-licenses --format=plain-vertical --with-license-file --no-license-path --with-urls --ignore-packages pip setuptools wheel pip-licenses pyinstaller pyinstaller-hooks-contrib > "$STAGE/usr/share/doc/$PKG/THIRD-PARTY-NOTICES.txt"
SIZE=$(du -sk "$STAGE/opt" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $DEBVER
Section: science
Priority: optional
Architecture: amd64
Installed-Size: $SIZE
Depends: libc6, libnss3, libxkbcommon0, libxcomposite1, libxdamage1, libxrandr2, libgbm1, libgl1, libegl1, libxcb-cursor0, libfontconfig1, libdbus-1-3, libasound2t64 | libasound2, libxcb-xinerama0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxcb-shape0
Maintainer: ZeravaTech Inc. <zerava.technologies@gmail.com>
Homepage: https://www.zeravatech.ca/products/pivot-benchmark/
Description: Pivot Benchmark - where an AI model breaks under social pressure
 One model (A) is pressured by another (B) along frozen ladders of praise that
 turns into insult, slander of a third party, or requests to deceive. Runs a
 local GGUF model through llama.cpp (installed separately) with Gemini as B.
EOF
mkdir -p dist/release
fakeroot dpkg-deb --build --root-owner-group "$STAGE" "dist/release/$OUT" 2>/dev/null \
  || dpkg-deb --build --root-owner-group "$STAGE" "dist/release/$OUT"
ls -lh "dist/release/$OUT"
(cd dist/release && sha256sum "$OUT" | tee -a SHA256SUMS.txt)     # bare file name, so sha256sum -c works beside the file
echo "DEB DONE"
