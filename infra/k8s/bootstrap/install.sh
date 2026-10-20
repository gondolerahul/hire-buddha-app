#!/usr/bin/env bash
# Bootstrap a HireBuddha AKS cluster (Phase 14 WS0 0.4) so that
# `helm upgrade --install hb-platform` can run on it. Idempotent: run it again
# after changing a version or a value.
#
#   bash infra/k8s/bootstrap/install.sh dev
#
# Needs: kubectl pointed at the cluster (az aks get-credentials + kubelogin),
# helm 3, and infra/azure/env/<env>.env filled in (SUFFIX, TENANT_ID,
# CLIENT_ID_* from the Bicep outputs) plus HB_ACME_EMAIL in the environment.
#
# Installs, in order:
#   1. Envoy Gateway (brings the Gateway API CRDs)
#   2. cert-manager with Gateway API support
#   3. hb-bootstrap: namespaces, sa-<id> service accounts with their workload
#      identities, the platform Gateway and its TLS, the OpenTelemetry Collector
set -euo pipefail

ENV_NAME="${1:-dev}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
ENV_FILE="$REPO_ROOT/infra/azure/env/$ENV_NAME.env"
VALUES_FILE="$REPO_ROOT/infra/k8s/env/$ENV_NAME/hb-bootstrap.yaml"
CHART="$REPO_ROOT/infra/k8s/charts/hb-bootstrap"

# Pinned; bump deliberately (each at least two weeks old when chosen).
ENVOY_GATEWAY_VERSION="v1.2.4"
CERT_MANAGER_VERSION="v1.16.2"

die() { echo "install.sh: $*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || die "missing $ENV_FILE (copy the names from the setup guide §2)"
[ -f "$VALUES_FILE" ] || die "missing $VALUES_FILE"
# shellcheck disable=SC1090
source "$ENV_FILE"
for name in TENANT_ID KV CLIENT_ID_API CLIENT_ID_WORKER CLIENT_ID_MIGRATOR; do
  value="${!name:-}"
  if [ -z "$value" ] || [[ "$value" == "<"* ]]; then
    die "$name is not set in $ENV_FILE"
  fi
done
[ -n "${HB_ACME_EMAIL:-}" ] || die "set HB_ACME_EMAIL (Let's Encrypt account e-mail)"

kubectl version --client >/dev/null || die "kubectl not found"
# Helm 4 applies server-side by default, which conflicts with fields AKS's
# admissions enforcer owns (cert-manager's webhook namespaceSelector): apply
# client-side, as Helm 3 does.
HELM_APPLY=()
case "$(helm version --short 2>/dev/null)" in
  v3.*) ;;
  v*) HELM_APPLY=(--server-side=false) ;;
esac
kubectl get --raw /readyz >/dev/null || die "kubectl cannot reach the cluster"

echo "== 1/3 Envoy Gateway $ENVOY_GATEWAY_VERSION"
helm upgrade --install eg oci://docker.io/envoyproxy/gateway-helm "${HELM_APPLY[@]}" \
  --version "$ENVOY_GATEWAY_VERSION" -n envoy-gateway-system --create-namespace --wait

echo "== 2/3 cert-manager $CERT_MANAGER_VERSION"
helm repo add jetstack https://charts.jetstack.io --force-update >/dev/null
helm upgrade --install cert-manager jetstack/cert-manager "${HELM_APPLY[@]}" \
  --version "$CERT_MANAGER_VERSION" -n cert-manager --create-namespace --wait \
  --set crds.enabled=true \
  --set config.apiVersion=controller.config.cert-manager.io/v1alpha1 \
  --set config.kind=ControllerConfiguration \
  --set config.enableGatewayAPI=true

echo "== 3/3 hb-bootstrap"
kubectl create namespace hb-system --dry-run=client -o yaml | kubectl apply -f -
kubectl label namespace hb-system pod-security.kubernetes.io/enforce=baseline --overwrite >/dev/null

# Client ids the identities' sa-<id> accounts sign in as (Bicep output identityClientIds).
identity_args=()
for id in api worker connsvc provisioner migrator appcontroller; do
  var="CLIENT_ID_$(echo "$id" | tr '[:lower:]' '[:upper:]')"
  value="${!var:-}"
  if [ -n "$value" ] && [[ "$value" != "<"* ]]; then
    identity_args+=(--set-string "serviceAccounts.$id.annotations.azure\.workload\.identity/client-id=$value")
  fi
done

helm upgrade --install hb-bootstrap "$CHART" -n hb-system "${HELM_APPLY[@]}" \
  -f "$CHART/values-azure.yaml" -f "$VALUES_FILE" \
  --set-string "env=$ENV_NAME" \
  --set-string "certManager.issuer.email=$HB_ACME_EMAIL" \
  --set-string "otelCollector.keyVault.name=$KV" \
  --set-string "otelCollector.keyVault.tenantId=$TENANT_ID" \
  --set-string "otelCollector.keyVault.clientId=$CLIENT_ID_WORKER" \
  "${identity_args[@]}" \
  --wait

echo
echo "Done. The platform gateway's address:"
kubectl -n hb-system get gateway platform-gateway -o jsonpath='{.status.addresses[*].value}{"\n"}' || true
echo "Point the DNS names of $VALUES_FILE at it; certificates follow once they resolve."
