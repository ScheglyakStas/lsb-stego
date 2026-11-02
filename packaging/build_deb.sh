#!/usr/bin/env bash
# Сборка пакета .deb: PyInstaller-бандл в /opt/lsb-stego + ярлык и значок.
# Использование: packaging/build_deb.sh [версия]   (из корня репозитория)
set -euo pipefail

VERSION="${1:-1.0.0}"
NAME=lsb-stego
ARCH=amd64
PKG="build/deb/${NAME}_${VERSION}_${ARCH}"

rm -rf build/pyinstaller "$PKG"
pyinstaller --noconfirm --clean --windowed \
    --name "$NAME" \
    --add-data "$PWD/assets/icon.png:assets" \
    --distpath build/pyinstaller/dist \
    --workpath build/pyinstaller/work \
    --specpath build/pyinstaller \
    main.py

mkdir -p "$PKG/DEBIAN" "$PKG/opt" "$PKG/usr/bin" \
         "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/256x256/apps"
cp -a "build/pyinstaller/dist/$NAME" "$PKG/opt/$NAME"
ln -s "/opt/$NAME/$NAME" "$PKG/usr/bin/$NAME"
install -m 644 packaging/lsb-stego.desktop "$PKG/usr/share/applications/$NAME.desktop"
install -m 644 assets/icon.png "$PKG/usr/share/icons/hicolor/256x256/apps/$NAME.png"

SIZE_KB=$(du -sk --exclude=DEBIAN "$PKG" | cut -f1)
cat > "$PKG/DEBIAN/control" <<EOF
Package: $NAME
Version: $VERSION
Section: graphics
Priority: optional
Architecture: $ARCH
Installed-Size: $SIZE_KB
Depends: libc6 (>= 2.35), libgl1, libegl1, libfontconfig1, libxkbcommon0, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-keysyms1, libxcb-shape0, libdbus-1-3
Maintainer: ScheglyakStas <ScheglyakStas@users.noreply.github.com>
Homepage: https://github.com/ScheglyakStas/lsb-stego
Description: LSB-стеганография в изображениях BMP
 Приложение для встраивания текстовых сообщений в изображения BMP методом
 замены младших битов (LSB) с выбором цветовых компонент, битовых плоскостей
 (1-4) и интервала встраивания, а также для их извлечения.
EOF

find "$PKG" -type d -exec chmod 755 {} +
mkdir -p dist
dpkg-deb --root-owner-group --build "$PKG" "dist/${NAME}_${VERSION}_${ARCH}.deb"
