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
    'wl-clipboard'
    'libnotify'
)
optdepends=(
    'hyprland: Native Wayland compositor support & socket IPC'
    'at-spi2-core: Native Linux accessibility D-Bus tree inspection (org.a11y.atspi)'
    'wl-screenrec: Hardware-accelerated 60 FPS DMA-BUF / PipeWire screen recording (VA-API / NVENC)'
    'wf-recorder: wlr-screencopy PipeWire screen recording fallback'
    'ffmpeg: High-quality animated WebP/GIF hardware transcoding'
    'tesseract: High-speed local offline streaming OCR'
    'wtype: Wayland keyboard dispatch fallback'
    'ydotool: Virtual uinput daemon fallback'
    'playerctl: Wayland MPRIS media controller fallback'
)
makedepends=(
    'python-build'
    'python-installer'
    'python-setuptools'
    'python-wheel'
)
source=()
sha256sums=()

build() {
    cd "$startdir"
    python -m build --wheel --no-isolation
}

package() {
    cd "$startdir"
    python -m installer --destdir="$pkgdir" dist/*.whl

    # Install udev rule for non-root /dev/uinput access
    install -Dm644 assets/99-aimvr-uinput.rules "$pkgdir/usr/lib/udev/rules.d/99-aimvr-uinput.rules"
}
