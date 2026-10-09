#!/usr/bin/env bash
# Fails if any ELF file under the given paths needs a glibc symbol newer than the baseline
# (R31: Ubuntu 22.04 = glibc 2.35). Prints the newest version each file needs.
#
# usage: packaging/check_glibc.sh PATH... [--max 2.35]
set -euo pipefail

max="2.35"
paths=()
while (($#)); do
  case "$1" in
    --max) max="$2"; shift 2 ;;
    *) paths+=("$1"); shift ;;
  esac
done
((${#paths[@]})) || { echo "usage: check_glibc.sh PATH... [--max 2.35]" >&2; exit 2; }

newest_overall="0"
checked=0
bad=0
while IFS= read -r -d '' file; do
  # Only ELF files (executables and shared libraries).
  [[ "$(head -c 4 "$file" | od -An -c | tr -d ' ')" == '177ELF' ]] || continue
  checked=$((checked + 1))
  newest="$(objdump -T "$file" 2>/dev/null | grep -o 'GLIBC_[0-9][0-9.]*' | sed 's/GLIBC_//' \
    | sort -V | tail -n 1 || true)"
  [[ -n "$newest" ]] || continue
  if [[ "$(printf '%s\n%s\n' "$newest" "$newest_overall" | sort -V | tail -n 1)" == "$newest" ]]; then
    newest_overall="$newest"
  fi
  if [[ "$(printf '%s\n%s\n' "$newest" "$max" | sort -V | tail -n 1)" != "$max" ]]; then
    echo "TOO NEW  glibc $newest  $file"
    bad=$((bad + 1))
  fi
done < <(find "${paths[@]}" -type f -print0)

echo "checked $checked ELF files; newest glibc symbol required: $newest_overall (limit $max)"
if ((bad)); then
  echo "error: $bad file(s) need glibc newer than $max" >&2
  exit 1
fi
