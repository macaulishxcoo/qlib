#!/usr/bin/env bash
# Make lightgbm importable without sudo.
#
# lightgbm's native library links against libgomp.so.1 (the GCC OpenMP runtime),
# which is not installed on this minimal Ubuntu and cannot be apt-installed
# without a password. Instead: download the .deb, extract it into ~/.local, and
# put that directory on the loader path.
set -uo pipefail

LIBDIR="${HOME}/.local/lib"
mkdir -p "${LIBDIR}" /tmp/libgomp-fix
cd /tmp/libgomp-fix

if [ -e "${LIBDIR}/libgomp.so.1" ]; then
  echo "libgomp already staged at ${LIBDIR}/libgomp.so.1"
else
  echo "downloading libgomp1 .deb (no sudo needed for apt-get download)"
  rm -f libgomp1*.deb
  if ! apt-get download libgomp1 >/dev/null 2>&1; then
    echo "apt-get download failed; trying a direct archive fetch"
    url=$(timeout 30 curl -4 -fsSL "http://archive.ubuntu.com/ubuntu/pool/main/g/gcc-14/" 2>/dev/null \
          | grep -o 'libgomp1_[^"]*amd64\.deb' | sort -u | tail -1)
    if [ -n "${url}" ]; then
      curl -4 -fsSL -o "libgomp1.deb" "http://archive.ubuntu.com/ubuntu/pool/main/g/gcc-14/${url}"
    fi
  fi

  deb=$(ls libgomp1*.deb 2>/dev/null | head -1)
  if [ -z "${deb}" ]; then
    echo "FAILED: could not obtain libgomp1"
    exit 1
  fi
  echo "extracting ${deb}"
  rm -rf extracted
  dpkg -x "${deb}" extracted
  found=$(find extracted -name 'libgomp.so.1*' | head -1)
  if [ -z "${found}" ]; then
    echo "FAILED: libgomp.so.1 not found inside the package"
    exit 1
  fi
  cp -a "$(dirname "${found}")"/libgomp.so.1* "${LIBDIR}/"
  echo "staged: $(ls -1 "${LIBDIR}"/libgomp.so.1* | tr '\n' ' ')"
fi

# Persist the loader path for interactive use.
ACT="${HOME}/qlib-env/bin/activate"
if [ -f "${ACT}" ] && ! grep -q 'LD_LIBRARY_PATH.*\.local/lib' "${ACT}"; then
  printf '\nexport LD_LIBRARY_PATH="${HOME}/.local/lib:${LD_LIBRARY_PATH:-}"\n' >> "${ACT}"
  echo "appended LD_LIBRARY_PATH to ${ACT}"
fi

echo
echo "verifying lightgbm import with LD_LIBRARY_PATH set:"
LD_LIBRARY_PATH="${LIBDIR}:${LD_LIBRARY_PATH:-}" "${HOME}/qlib-env/bin/python" - <<'PYEOF'
try:
    import lightgbm
    print("  lightgbm OK", lightgbm.__version__)
except Exception as exc:
    print("  lightgbm FAILED:", type(exc).__name__, exc)
PYEOF
