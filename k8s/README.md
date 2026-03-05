# Kubernetes Manifests

## Quick Start

```bash
# 1. Update values marked with "UPDATE" comments in:
#    - configmap.yaml (ClickHouse host)
#    - deployment.yaml (ECR image)
#    - ingress.yaml (domain, certificate ARN)

# 2. Apply in order
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml
kubectl apply -f external-secret.yaml   # or secret.yaml if not using External Secrets
kubectl apply -f serviceaccount.yaml
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
kubectl apply -f ingress.yaml
kubectl apply -f hpa.yaml
kubectl apply -f pdb.yaml

# 3. Verify
kubectl -n recommendations get pods
kubectl -n recommendations logs -l app=twc-recommendations
```

## Files

| File | Purpose |
|------|---------|
| `namespace.yaml` | Creates the `recommendations` namespace |
| `configmap.yaml` | Non-sensitive configuration |
| `external-secret.yaml` | Syncs secrets from AWS Secrets Manager |
| `secret.yaml.example` | Manual secret template (not recommended) |
| `serviceaccount.yaml` | Service account for IRSA |
| `deployment.yaml` | Main deployment with 3 replicas |
| `service.yaml` | ClusterIP service |
| `ingress.yaml` | ALB ingress for external access |
| `hpa.yaml` | Horizontal Pod Autoscaler (3-10 pods) |
| `pdb.yaml` | Pod Disruption Budget (min 2 available) |

## Required Updates

Before deploying, update these placeholders:

1. **configmap.yaml**: `CLICKHOUSE_HOST` - your ClickHouse hostname
2. **deployment.yaml**: `image` - your ECR repository and tag
3. **ingress.yaml**: `certificate-arn` - your ACM certificate
4. **ingress.yaml**: `host` - your internal domain

## Full Documentation

See `docs/DEVOPS_DEPLOYMENT_GUIDE.md` for complete instructions.
