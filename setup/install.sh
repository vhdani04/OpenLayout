#!/usr/bin/env bash
# Reproducible install of the OpenLayout.
#   setup/install.sh [all|deps|tools|pdk|models|views|python|desktop|shell]   (default: all; every step is idempotent)
set -euo pipefail
FLOW="$(cd "$(dirname "$0")/.." && pwd)"
source "$FLOW/setup/versions.env"
source "$FLOW/env/openlayout.sh"
SRC="$OPENLAYOUT_ROOT/src"
JOBS=$(nproc)
mkdir -p "$SRC" "$PDK_ROOT" "$OPENLAYOUT_MODELS"

step() { echo; echo "==== $* ($(date +%T))"; }
have_version() { command -v "$1" >/dev/null && "$1" "${@:3}" 2>&1 | grep -q "$2"; }

do_deps() {
  step "apt dependencies"
  sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    build-essential git curl wget pkg-config autoconf automake libtool flex bison gawk m4 \
    cmake ninja-build python3 python3-pip python3-venv python3-dev \
    libx11-dev libxrender-dev libxpm-dev libxcb1-dev libx11-xcb-dev libcairo2-dev libjpeg-dev \
    tcl-dev tk-dev tcl8.6-dev tk8.6-dev tcllib libxaw7-dev libreadline-dev libfftw3-dev \
    libgomp1 libncurses-dev xterm gedit xvfb \
    libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 > /dev/null
}

do_tools() {
  cd "$SRC"
  step "KLayout $KLAYOUT_VERSION"
  if have_version klayout "KLayout $KLAYOUT_VERSION" -v; then echo "already installed"; else
    deb="klayout_${KLAYOUT_VERSION}-1_amd64.deb"
    wget -q -N "https://www.klayout.org/downloads/Ubuntu-24/$deb"
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "./$deb" > /dev/null
  fi

  step "OpenVAF-reloaded ($OPENVAF_BUILD)"
  if [ -f "/usr/local/share/openvaf-r.build" ] && grep -qx "$OPENVAF_BUILD" /usr/local/share/openvaf-r.build; then
    echo "already installed"
  else
    wget -q -N "https://fides.fe.uni-lj.si/openvaf/download/$OPENVAF_BUILD-linux_x64.tar.gz"
    rm -rf openvaf && mkdir openvaf && tar -xzf "$OPENVAF_BUILD-linux_x64.tar.gz" -C openvaf
    sudo install -m 755 "$(find openvaf -type f -name 'openvaf*' -perm -u+x | head -1)" /usr/local/bin/openvaf-r
    echo "$OPENVAF_BUILD" | sudo tee /usr/local/share/openvaf-r.build > /dev/null
  fi

  step "ngspice $NGSPICE_VERSION (with OSDI)"
  if have_version ngspice "ngspice-$NGSPICE_VERSION" -v; then echo "already installed"; else
    wget -q -O "ngspice-$NGSPICE_VERSION.tar.gz" \
      "https://sourceforge.net/projects/ngspice/files/ng-spice-rework/$NGSPICE_VERSION/ngspice-$NGSPICE_VERSION.tar.gz/download"
    rm -rf "ngspice-$NGSPICE_VERSION" && tar -xzf "ngspice-$NGSPICE_VERSION.tar.gz"
    mkdir -p "ngspice-$NGSPICE_VERSION/release" && cd "ngspice-$NGSPICE_VERSION/release"
    ../configure --prefix=/usr/local --with-x --enable-xspice --enable-cider --enable-osdi \
      --enable-openmp --enable-predictor --with-readline=yes --disable-debug CFLAGS="-O2" > configure.log
    make -j"$JOBS" > make.log 2>&1 && sudo make install > install.log
    cd "$SRC"
  fi

  step "xschem @ $XSCHEM_REF"
  [ -d xschem ] || git clone -q https://github.com/StefanSchippers/xschem.git
  # OpenLayout patches (setup/patches/xschem-*.patch) go on top of the pinned release
  xschem_patched() {
    for p in "$FLOW"/setup/patches/xschem-*.patch; do
      git -C xschem apply --reverse --check "$p" 2>/dev/null || return 1
    done
  }
  if [ "$(git -C xschem rev-parse --short HEAD)" = "$XSCHEM_REF" ] && command -v xschem >/dev/null && xschem_patched; then
    echo "already installed"
  else
    git -C xschem fetch -q && git -C xschem checkout -q -f "$XSCHEM_REF"
    for p in "$FLOW"/setup/patches/xschem-*.patch; do git -C xschem apply "$p"; done
    (cd xschem && ./configure --prefix=/usr/local > configure.log && make -j"$JOBS" > make.log 2>&1 \
      && sudo make install > install.log)
  fi
}

do_pdk() {
  step "ASAP7 PDK + 7.5T standard cells"
  cd "$PDK_ROOT"
  [ -d asap7/.git ] || git clone -q --depth 1 https://github.com/The-OpenROAD-Project/asap7.git
  cd asap7
  for sm in asap7_pdk_r1p7 asap7sc7p5t_28; do
    if [ -n "$(ls -A "$sm" 2>/dev/null)" ]; then echo "$sm present"; else
      git submodule update --init --depth 1 "$sm"
    fi
  done
}

do_models() {
  step "BSIM-CMG OSDI model + ASAP7 ngspice cards"
  local d="$OPENLAYOUT_MODELS/bsimcmg"
  mkdir -p "$d"
  local base="https://raw.githubusercontent.com/$BSIMCMG_REPO/$BSIMCMG_REF/integration_tests/BSIMCMG"
  for f in LICENSE.txt NOTICE.txt bsimcmg.va bsimcmg_body.include bsimcmg_checking.include \
           bsimcmg_initialization.include bsimcmg_macros.include bsimcmg_noise.include \
           bsimcmg_parameters.include bsimcmg_variables.include; do
    [ -f "$d/$f" ] || curl -sfL -o "$d/$f" "$base/$f"
  done
  [ "$d/bsimcmg.osdi" -nt "$d/bsimcmg.va" ] || (cd "$d" && openvaf-r bsimcmg.va -o bsimcmg.osdi)
  python3 "$FLOW/pdk/asap7/ngspice/convert_asap7_models.py" "$ASAP7_PDK/models/hspice" "$ASAP7_SPICE_DIR"
  python3 "$FLOW/pdk/asap7/ngspice/convert_asap7_stdcells.py" "$ASAP7_STDCELLS" "$ASAP7_SPICE_DIR"
}

do_views() {
  step "Generated views (std-cell symbols, xschem theme)"
  python3 "$FLOW/share/theme/gen_xschem_theme.py"
  python3 "$FLOW/pdk/asap7/xschem/gen_stdcell_symbols.py" "$ASAP7_STDCELLS" "$OPENLAYOUT_ROOT/libs"
  # KLayout loads every layout in a technology's libraries/ folder as a library for that technology.
  local kl="$FLOW/pdk/asap7/klayout/tech/asap7/libraries"
  mkdir -p "$kl"
  for f in R L SL SRAM; do
    ln -sf "$(ls "$ASAP7_STDCELLS"/GDS/asap7sc7p5t_28_${f}_*.gds | head -1)" "$kl/asap7sc7p5t_28_${f}.gds"
  done
}

do_python() {
  step "Python environment (hub)"
  [ -x "$OPENLAYOUT_ROOT/venv/bin/python" ] || python3 -m venv "$OPENLAYOUT_ROOT/venv"
  "$OPENLAYOUT_ROOT/venv/bin/pip" install -q --upgrade pip
  "$OPENLAYOUT_ROOT/venv/bin/pip" install -q -r "$FLOW/python/requirements.txt"
}

do_desktop() {
  step "Desktop entry"
  local apps=~/.local/share/applications icons=~/.local/share/icons/hicolor/scalable/apps
  mkdir -p "$apps" "$icons"
  sed "s|@OPENLAYOUT_HOME@|$OPENLAYOUT_HOME|g" "$FLOW/share/applications/openlayout.desktop.in" > "$apps/openlayout.desktop"
  cp "$FLOW/share/icons/openlayout.svg" "$icons/openlayout.svg"
  command -v update-desktop-database > /dev/null && update-desktop-database -q "$apps" || true
  command -v gtk-update-icon-cache > /dev/null && gtk-update-icon-cache -q ~/.local/share/icons/hicolor || true
}

do_shell() {
  step "shell + ngspice init"
  local line="source \"$OPENLAYOUT_HOME/env/openlayout.sh\""
  grep -qxF "$line" ~/.bashrc || printf '\n# OpenLayout\n%s\n' "$line" >> ~/.bashrc
  # ngspice reads ~/.spiceinit at startup: load BSIM-CMG and make the ASAP7 cards findable.
  local begin="* >>> openlayout (managed by $OPENLAYOUT_HOME/setup/install.sh) >>>" end="* <<< openlayout <<<"
  touch ~/.spiceinit
  sed -i "/^\* >>> openlayout/,/^\* <<< openlayout/d" ~/.spiceinit
  cat >> ~/.spiceinit <<EOS
$begin
osdi $BSIMCMG_OSDI
set sourcepath = ( . $ASAP7_SPICE_DIR )
set num_threads = $JOBS
$end
EOS
}

case "${1:-all}" in
  all)    do_deps; do_tools; do_pdk; do_models; do_views; do_python; do_desktop; do_shell ;;
  deps)   do_deps ;;
  tools)  do_tools ;;
  pdk)    do_pdk ;;
  models) do_models ;;
  views)  do_views ;;
  python) do_python ;;
  desktop) do_desktop ;;
  shell)  do_shell ;;
  *) echo "usage: $0 [all|deps|tools|pdk|models|views|python|desktop|shell]"; exit 1 ;;
esac
step "done"
