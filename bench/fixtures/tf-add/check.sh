#!/usr/bin/env bash
set -uo pipefail
terraform fmt -check -recursive . || { echo "FAIL: not fmt clean"; exit 1; }
grep -qE 'variable[[:space:]]+"environment"' variables.tf || { echo "FAIL: no environment variable"; exit 1; }
grep -A4 -E 'variable[[:space:]]+"environment"' variables.tf | grep -q 'type *= *string' || { echo "FAIL: environment not typed string"; exit 1; }
grep -A4 -E 'variable[[:space:]]+"environment"' variables.tf | grep -q 'description' || { echo "FAIL: environment has no description"; exit 1; }
grep -A4 -E 'variable[[:space:]]+"environment"' variables.tf | grep -q 'default' && { echo "FAIL: environment must not have a default"; exit 1; }
grep -q 'var.project}-${var.environment}' locals.tf || { echo "FAIL: name_prefix not project-environment"; exit 1; }
grep -q 'local.name_prefix' outputs.tf || { echo "FAIL: output broken"; exit 1; }
echo PASS
