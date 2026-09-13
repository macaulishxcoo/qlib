#!/usr/bin/env bash
# Syntax-check every Python file in the repo after the path-porting edits.
# A broken rewrite would otherwise only surface when that script is next run.
PY="${HOME}/qlib-env/bin/python"
REPO=/mnt/d/workspaces/qlib

cd "${REPO}" || exit 1
echo "compiling scripts/ and research/ ..."
fail=0
count=0
while IFS= read -r f; do
  count=$((count + 1))
  if ! "${PY}" -m py_compile "$f" 2>/tmp/pycompile.err; then
    fail=$((fail + 1))
    echo "  SYNTAX ERROR: $f"
    sed -n '1,4p' /tmp/pycompile.err | sed 's/^/      /'
  fi
done < <(find scripts research -name '*.py' -not -path '*/__pycache__/*' 2>/dev/null)

echo "checked ${count} files, ${fail} failed"
exit $((fail > 0 ? 1 : 0))
