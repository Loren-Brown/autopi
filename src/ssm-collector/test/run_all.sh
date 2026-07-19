#!/usr/bin/env bash
# Run every Python test script under ssm-collector/test/.
# Extra args are forwarded to each script (e.g. --offline).
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${TEST_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"

shopt -s nullglob
scripts=("${TEST_DIR}"/*.py)
if [[ ${#scripts[@]} -eq 0 ]]; then
  echo "No test scripts found in ${TEST_DIR}" >&2
  exit 1
fi

failed=0
for script in "${scripts[@]}"; do
  echo ""
  echo "════════════════════════════════════════════════════════════"
  echo " Running $(basename "${script}")"
  echo "════════════════════════════════════════════════════════════"
  if uv run "${script}" "$@"; then
    echo "OK: $(basename "${script}")"
  else
    echo "FAIL: $(basename "${script}") (exit $?)" >&2
    failed=1
  fi
done

echo ""
if [[ "${failed}" -ne 0 ]]; then
  echo "ssm-collector tests: FAILED" >&2
  exit 1
fi
echo "ssm-collector tests: all passed"
