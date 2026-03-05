# TWC Recommendations - DevOps Deployment Guide

**Service:** twc-recommendations
**Target:** AWS EKS (Kubernetes)
**Last Updated:** March 2025

---

## Table of Contents

1. [Service Overview](#service-overview)
2. [Prerequisites](#prerequisites)
3. [Docker Build](#docker-build)
4. [Environment Variables](#environment-variables)
5. [Kubernetes Manifests](#kubernetes-manifests)
6. [AWS Infrastructure](#aws-infrastructure)
7. [Health Checks](#health-checks)
8. [Resource Requirements](#resource-requirements)
9. [Networking & Security](#networking--security)
10. [Monitoring & Logging](#monitoring--logging)
11. [Deployment Checklist](#deployment-checklist)
12. [Troubleshooting](#troubleshooting)

---

## Service Overview

| Property | Value |
|----------|-------|
| **Service Name** | twc-recommendations |
| **Language** | Python 3.13 |
| **Framework** | FastAPI |
| **Port** | 8000 |
| **Protocol** | HTTP (TLS terminated at ALB) |
| **Database** | ClickHouse (read-only) |
| **State** | Stateless |

**What it does:** Returns personalized product recommendations for retail customers. Reads customer profiles and product catalog from ClickHouse, scores products in-memory, returns JSON.

**Traffic pattern:** Synchronous request/response. No background jobs, no queues, no write operations.

---

## Prerequisites

- AWS EKS cluster
- ECR repository for container images
- ClickHouse cluster accessible from EKS
- AWS Secrets Manager or external-secrets-operator for credentials
- ALB Ingress Controller (or similar)

---

## Docker Build

### Dockerfile

Create `Dockerfile` in project root:

```dockerfile
FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/

# Create non-root user
RUN useradd --create-home appuser
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"

# Run with uvicorn
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### Build & Push to ECR

```bash
# Set variables
AWS_ACCOUNT_ID=123456789012
AWS_REGION=ap-southeast-2
ECR_REPO=twc-recommendations
IMAGE_TAG=$(git rev-parse --short HEAD)

# Authenticate to ECR
aws ecr get-login-password --region $AWS_REGION | \
    docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Build
docker build -t $ECR_REPO:$IMAGE_TAG .

# Tag
docker tag $ECR_REPO:$IMAGE_TAG $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:$IMAGE_TAG

# Push
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:$IMAGE_TAG
```

---

## Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `CLICKHOUSE_HOST` | Yes | ClickHouse server hostname | `clickhouse.twc.internal` |
| `CLICKHOUSE_PORT` | No | HTTP port (default: 8443) | `8443` |
| `CLICKHOUSE_USER` | Yes | Username | `recommendations_ro` |
| `CLICKHOUSE_PASSWORD` | Yes | Password (use Secret) | `***` |
| `CLICKHOUSE_DATABASE` | No | Database name (default: default) | `default` |
| `CLICKHOUSE_SECURE` | No | Use HTTPS (default: true) | `true` |
| `LOG_LEVEL` | No | Logging level (default: INFO) | `INFO` |
| `WORKERS` | No | Uvicorn worker count (default: 4) | `4` |

**Sensitive variables** (`CLICKHOUSE_PASSWORD`) must come from Kubernetes Secrets, not ConfigMaps.

---

## Kubernetes Manifests

### Namespace

```yaml
# namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: recommendations
  labels:
    app.kubernetes.io/name: twc-recommendations
```

### ConfigMap

```yaml
# configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: twc-recommendations-config
  namespace: recommendations
data:
  CLICKHOUSE_HOST: "clickhouse.twc.internal"
  CLICKHOUSE_PORT: "8443"
  CLICKHOUSE_DATABASE: "default"
  CLICKHOUSE_SECURE: "true"
  CLICKHOUSE_USER: "recommendations_ro"
  LOG_LEVEL: "INFO"
```

### Secret (via External Secrets Operator)

```yaml
# external-secret.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: twc-recommendations-secrets
  namespace: recommendations
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: twc-recommendations-secrets
    creationPolicy: Owner
  data:
    - secretKey: CLICKHOUSE_PASSWORD
      remoteRef:
        key: twc/recommendations/clickhouse
        property: password
```

Or create manually (not recommended for production):

```yaml
# secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: twc-recommendations-secrets
  namespace: recommendations
type: Opaque
stringData:
  CLICKHOUSE_PASSWORD: "your-password-here"
```

### Deployment

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: twc-recommendations
  namespace: recommendations
  labels:
    app: twc-recommendations
spec:
  replicas: 3
  selector:
    matchLabels:
      app: twc-recommendations
  template:
    metadata:
      labels:
        app: twc-recommendations
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: twc-recommendations
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      containers:
        - name: twc-recommendations
          image: 123456789012.dkr.ecr.ap-southeast-2.amazonaws.com/twc-recommendations:latest
          imagePullPolicy: Always
          ports:
            - name: http
              containerPort: 8000
              protocol: TCP
          envFrom:
            - configMapRef:
                name: twc-recommendations-config
            - secretRef:
                name: twc-recommendations-secrets
          resources:
            requests:
              cpu: "250m"
              memory: "512Mi"
            limits:
              cpu: "1000m"
              memory: "1Gi"
          livenessProbe:
            httpGet:
              path: /api/v1/health
              port: http
            initialDelaySeconds: 10
            periodSeconds: 30
            timeoutSeconds: 5
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /api/v1/health
              port: http
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 3
            failureThreshold: 3
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop:
                - ALL
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app: twc-recommendations
                topologyKey: topology.kubernetes.io/zone
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              app: twc-recommendations
```

### Service

```yaml
# service.yaml
apiVersion: v1
kind: Service
metadata:
  name: twc-recommendations
  namespace: recommendations
  labels:
    app: twc-recommendations
spec:
  type: ClusterIP
  ports:
    - name: http
      port: 80
      targetPort: http
      protocol: TCP
  selector:
    app: twc-recommendations
```

### Ingress (ALB)

```yaml
# ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: twc-recommendations
  namespace: recommendations
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internal
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/healthcheck-path: /api/v1/health
    alb.ingress.kubernetes.io/healthcheck-interval-seconds: "30"
    alb.ingress.kubernetes.io/healthy-threshold-count: "2"
    alb.ingress.kubernetes.io/unhealthy-threshold-count: "3"
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'
    alb.ingress.kubernetes.io/ssl-redirect: "443"
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:ap-southeast-2:123456789012:certificate/xxx
spec:
  rules:
    - host: recommendations.internal.twc.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: twc-recommendations
                port:
                  number: 80
```

### Horizontal Pod Autoscaler

```yaml
# hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: twc-recommendations
  namespace: recommendations
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: twc-recommendations
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 25
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Percent
          value: 100
          periodSeconds: 30
```

### ServiceAccount (for IRSA if needed)

```yaml
# serviceaccount.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: twc-recommendations
  namespace: recommendations
  annotations:
    # Only needed if accessing AWS services (e.g., Secrets Manager directly)
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/twc-recommendations-role
```

### PodDisruptionBudget

```yaml
# pdb.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: twc-recommendations
  namespace: recommendations
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: twc-recommendations
```

---

## AWS Infrastructure

### ECR Repository

```bash
aws ecr create-repository \
    --repository-name twc-recommendations \
    --image-scanning-configuration scanOnPush=true \
    --encryption-configuration encryptionType=AES256 \
    --region ap-southeast-2
```

### Secrets Manager

```bash
aws secretsmanager create-secret \
    --name twc/recommendations/clickhouse \
    --secret-string '{"password":"your-clickhouse-password"}' \
    --region ap-southeast-2
```

### IAM Role for Service Account (IRSA)

If using External Secrets Operator to fetch from Secrets Manager:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:twc/recommendations/*"
    }
  ]
}
```

---

## Health Checks

| Check | Endpoint | Expected Response |
|-------|----------|-------------------|
| Liveness | `GET /api/v1/health` | `{"status": "healthy", "service": "twc-recommendations"}` |
| Readiness | `GET /api/v1/health` | Same as above |
| ALB Target Group | `GET /api/v1/health` | HTTP 200 |

The health check does not verify ClickHouse connectivity (by design - it's a simple liveness check). If ClickHouse connectivity needs to be verified, a `/ready` endpoint could be added.

---

## Resource Requirements

### Per Pod

| Resource | Request | Limit | Notes |
|----------|---------|-------|-------|
| CPU | 250m | 1000m | Mostly CPU-bound (scoring algorithm) |
| Memory | 512Mi | 1Gi | Loads product catalog into memory |

### Scaling

| Metric | Threshold | Notes |
|--------|-----------|-------|
| Min replicas | 3 | Spread across AZs |
| Max replicas | 10 | Adjust based on load testing |
| CPU target | 70% | HPA trigger |

### Expected Performance

| Metric | Target |
|--------|--------|
| P50 latency | < 100ms |
| P95 latency | < 300ms |
| P99 latency | < 500ms |
| Requests/pod | ~100 RPS |

---

## Networking & Security

### Inbound

| Source | Port | Protocol | Purpose |
|--------|------|----------|---------|
| ALB | 8000 | HTTP | API traffic |
| Prometheus | 8000 | HTTP | Metrics scraping |

### Outbound

| Destination | Port | Protocol | Purpose |
|-------------|------|----------|---------|
| ClickHouse | 8443 | HTTPS | Database queries |

### Security Groups

**Pod Security Group** (if using Security Groups for Pods):

```
Inbound:
  - Port 8000 from ALB security group
  - Port 8000 from Prometheus security group

Outbound:
  - Port 8443 to ClickHouse security group
  - Port 443 to 0.0.0.0/0 (for ECR image pulls)
```

### Network Policy (optional)

```yaml
# network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: twc-recommendations
  namespace: recommendations
spec:
  podSelector:
    matchLabels:
      app: twc-recommendations
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: ingress-nginx
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - protocol: TCP
          port: 8000
  egress:
    - to:
        - ipBlock:
            cidr: 10.0.0.0/8  # Internal network for ClickHouse
      ports:
        - protocol: TCP
          port: 8443
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: UDP
          port: 53  # DNS
```

---

## Monitoring & Logging

### Logs

- **Format:** JSON (structured logging)
- **Output:** stdout
- **Collection:** Fluent Bit → CloudWatch Logs or your logging stack

### Metrics

FastAPI exposes Prometheus metrics at `/metrics` (if prometheus-fastapi-instrumentator is added). Key metrics:

| Metric | Description |
|--------|-------------|
| `http_requests_total` | Request count by endpoint, status |
| `http_request_duration_seconds` | Request latency histogram |
| `http_requests_in_progress` | Current concurrent requests |

### CloudWatch Alarms (suggested)

| Alarm | Condition | Action |
|-------|-----------|--------|
| High Error Rate | 5xx > 1% for 5 min | PagerDuty |
| High Latency | P95 > 500ms for 5 min | Slack |
| Pod Restarts | > 3 in 10 min | Slack |
| Low Available Pods | < 2 for 5 min | PagerDuty |

### Dashboards

Create Grafana dashboard with:
- Request rate by endpoint
- Error rate by endpoint
- Latency percentiles (P50, P95, P99)
- Pod CPU/memory usage
- ClickHouse query latency (if instrumented)

---

## Deployment Checklist

### Pre-deployment

- [ ] ECR repository created
- [ ] Docker image built and pushed
- [ ] ClickHouse read-only user created (`recommendations_ro`)
- [ ] ClickHouse network accessible from EKS
- [ ] Secrets stored in AWS Secrets Manager
- [ ] External Secrets Operator configured (if using)
- [ ] SSL certificate in ACM for ingress domain

### Deployment

```bash
# Apply manifests in order
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml
kubectl apply -f external-secret.yaml  # or secret.yaml
kubectl apply -f serviceaccount.yaml
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
kubectl apply -f ingress.yaml
kubectl apply -f hpa.yaml
kubectl apply -f pdb.yaml

# Verify
kubectl -n recommendations get pods
kubectl -n recommendations logs -l app=twc-recommendations --tail=50
```

### Post-deployment Verification

```bash
# Check pods are running
kubectl -n recommendations get pods

# Check health endpoint (port-forward)
kubectl -n recommendations port-forward svc/twc-recommendations 8080:80
curl http://localhost:8080/api/v1/health

# Check via ingress (after DNS propagation)
curl https://recommendations.internal.twc.com/api/v1/health

# Test with real customer
curl "https://recommendations.internal.twc.com/api/v1/recommendations/camillaandmarc-au/2905235947555"
```

---

## Troubleshooting

### Pod won't start

```bash
# Check events
kubectl -n recommendations describe pod <pod-name>

# Check logs
kubectl -n recommendations logs <pod-name>

# Common issues:
# - Image pull error: Check ECR permissions, image tag
# - Secret not found: Check external-secrets sync
# - CrashLoopBackOff: Check CLICKHOUSE_* env vars
```

### ClickHouse connection errors

```bash
# Exec into pod and test connectivity
kubectl -n recommendations exec -it <pod-name> -- /bin/sh

# Test DNS resolution
nslookup clickhouse.twc.internal

# Test port connectivity
nc -zv clickhouse.twc.internal 8443

# Common issues:
# - Security group blocking outbound 8443
# - ClickHouse hostname incorrect
# - Password incorrect (check secret value)
```

### High latency

```bash
# Check if it's ClickHouse or the service
# Add timing to a request
curl -w "@curl-timing.txt" "https://recommendations.internal.twc.com/api/v1/recommendations/tenant/customer"

# Check pod resources
kubectl -n recommendations top pods

# Common issues:
# - ClickHouse slow (check CH metrics)
# - Too few workers (increase WORKERS env var)
# - Pod resource limits too low
```

### 5xx errors

```bash
# Check application logs
kubectl -n recommendations logs -l app=twc-recommendations --tail=100 | grep -i error

# Common issues:
# - Customer not found (404 from API, but logged as error)
# - ClickHouse timeout
# - Out of memory (OOMKilled - increase limits)
```

---

## Contacts

| Role | Contact |
|------|---------|
| Service Owner | [Your team] |
| On-call | [PagerDuty service] |
| ClickHouse Admin | [DBA team] |

---

## Appendix: All Manifests in One File

For convenience, all manifests combined in `k8s/all-in-one.yaml`:

```bash
# Apply everything at once
kubectl apply -f k8s/all-in-one.yaml
```
