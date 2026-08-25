#!/usr/bin/env bash
# Fail if a source file declares adapted third-party code without a
# corresponding entry in THIRD_PARTY_NOTICES.md.
#
# Attribution that lives only in a code comment gets lost during refactors.
# This makes the notices file the single place a reviewer has to check.
#
# Convention: a file that contains adapted or vendored third-party code carries
# an explicit marker comment naming the source, for example
#
#     # THIRD-PARTY: Py1812 (ITU-R P.1812-8 reference implementation)
#
# The marker is deliberately unambiguous. An earlier version of this script
# grepped for the phrase "derived from", which matched ordinary prose in
# docstrings and produced false failures.
set -euo pipefail

notices="THIRD_PARTY_NOTICES.md"
marker="THIRD-PARTY:"
status=0
found=0

if [[ ! -f "$notices" ]]; then
  echo "error: $notices is missing" >&2
  exit 1
fi

while IFS= read -r line; do
  found=$((found + 1))
  file="${line%%:*}"
  source_name=$(sed -E "s/.*${marker}[[:space:]]*//; s/[[:space:]]*\(.*//; s/[[:space:]]*$//" <<<"$line")
  if [[ -z "$source_name" ]]; then
    echo "error: $file has a bare '$marker' marker with no source named" >&2
    status=1
    continue
  fi
  if ! grep -qiF "$source_name" "$notices"; then
    echo "error: $file credits '$source_name' but $notices has no entry for it" >&2
    status=1
  fi
done < <(grep -rn "$marker" src/ 2>/dev/null || true)

if [[ $status -eq 0 ]]; then
  echo "attribution check passed ($found third-party marker(s) found, all recorded)"
fi
exit $status
