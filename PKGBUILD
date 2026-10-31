# Maintainer: Arman <rangooniarman@gmail.com>
pkgname=python-computercontrol-aim-vr
_pkgname=computercontrol-aim-vr
pkgver=3.0.0
pkgrel=1
pkgdesc="Industrial SOTA Windows & Arch Linux (Hyprland Wayland) Computer Control & Desktop Automation System (AIM-VR 3.0)"
arch=('any')
url="https://github.com/Arman4464/computer-control-aim-vr"
license=('MIT')
depends=(
    'python'
    'python-pillow'
    'python-evdev'
    'grim'
    'libnotify'
)
optdepends=(
    'hyprland: Native Wayland compositor support & socket IPC'
    'at-spi2-core: Native Linux accessibility D-Bus tree inspection (org.a11y.atspi)'
    'tesseract-data-eng: In-memory Tesseract TSV OCR'
    'pipewire: PipeWire multimedia server for DMA-BUF capture'
    'wireplumber: Session manager for PipeWire'
    'wf-recorder: Hardware-accelerated 60 FPS screen recorder'
    'wl-screenrec: High-performance NVENC/DMA-BUF screen recorder'
    'wtype: Rootless virtual keyboard fallback'
    'wl-clipboard: Wayland clipboard provider'
    'ffmpeg: High-quality animated WebP/GIF hardware transcoding'
    'tesseract: High-speed local offline streaming OCR'
    'ydotool: Virtual uinput daemon fallback'
    'playerctl: Wayland MPRIS media controller fallback'
)
makedepends=(
    'python-build'
    'python-installer'
    'python-setuptools'
    'python-wheel'
)
checkdepends=(
    'python-pytest'
)
source=()
sha256sums=()

build() {
    cd "$srcdir"
    python -m build --wheel --no-isolation
}

check() {
    cd "$srcdir"
    python -m unittest tests/test_linux_sota.py tests/test_platform.py
}

package() {
    cd "$srcdir"
    python -m installer --destdir="$pkgdir" dist/*.whl

    # Install udev rule for non-root /dev/uinput access
    install -Dm644 assets/99-aimvr-uinput.rules "$pkgdir/usr/lib/udev/rules.d/99-aimvr-uinput.rules"

    # Install modules-load configuration to auto-load uinput at boot
    install -Dm644 assets/aimvr-uinput.conf "$pkgdir/usr/lib/modules-load.d/aimvr-uinput.conf"

    # Install MIT license
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
