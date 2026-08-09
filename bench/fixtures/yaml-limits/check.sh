#!/usr/bin/env bash
set -uo pipefail
command -v yq >/dev/null || { echo "SKIP: yq missing"; exit 1; }
q() { yq -r "$1" deployment.yaml; }
[ "$(q '.spec.template.spec.containers[0].resources.requests.cpu')" = "100m" ] || { echo "FAIL: cpu request"; exit 1; }
[ "$(q '.spec.template.spec.containers[0].resources.requests.memory')" = "128Mi" ] || { echo "FAIL: mem request"; exit 1; }
[ "$(q '.spec.template.spec.containers[0].resources.limits.cpu')" = "500m" ] || { echo "FAIL: cpu limit"; exit 1; }
[ "$(q '.spec.template.spec.containers[0].resources.limits.memory')" = "512Mi" ] || { echo "FAIL: mem limit"; exit 1; }
[ "$(q '.spec.replicas')" = "2" ] || { echo "FAIL: replicas changed"; exit 1; }
[ "$(q '.spec.template.spec.containers[0].image')" = "tracking-service:1.4.2" ] || { echo "FAIL: image changed"; exit 1; }
echo PASS
