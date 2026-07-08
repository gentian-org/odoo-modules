# Odoo Modules Management

This document explains how custom Odoo modules are managed in different environments.

## Overview

Custom modules are sourced from: `https://github.com/gentian-org/odoo-modules.git`

## Development Environment

**Strategy**: Direct hostPath mount for live development

- **Path**: `/path/to/your/odoo-modules` (configure in `overlays/dev/modules-volume-patch.yaml`)
- **Advantages**:
  - Instant module changes (no rebuild/redeploy)
  - Easy local development workflow
  - Can edit modules with local IDE
- **Disadvantages**:
  - Node-specific (only works where path exists)
  - Not portable across environments

**Usage**:
```bash
# Edit modules locally (wherever you cloned the repo)
cd /path/to/your/odoo-modules
# Make changes...

# Odoo will see changes immediately
# Restart Odoo pod to reload modules:
kubectl rollout restart -n gentian-server deployment/odoo
```

## Production Environment

**Strategy**: PVC with automated git synchronization

- **Update Frequency**: Every 15 minutes (configurable)
- **Storage**: PVC with ReadWriteMany access
- **Components**:
  - **PVC**: Persistent storage for modules
  - **Initial Clone Job**: Populates PVC on first deployment
  - **CronJob**: Pulls latest changes every 15 minutes

### How It Works

1. **Initial Deployment**:
   ```bash
   kubectl apply -k overlays/production
   ```
   - Creates PVC for modules
   - Runs Job to clone git repository
   - Mounts PVC to Odoo pods

2. **Automatic Updates**:
   - CronJob runs every 15 minutes
   - Pulls latest changes from git
   - If repo exists: `git pull`
   - If not: `git clone`
   - All Odoo pods see updated modules via shared PVC

3. **Module Activation**:
   - Push changes to git repository
   - Wait up to 15 minutes for sync
   - Update module list in Odoo UI
   - Or restart Odoo: `kubectl rollout restart -n gentian-server deployment/odoo`

### Customizing Update Frequency

Edit the CronJob schedule in `base/odoo/modules-updater-cronjob.yaml`:

```yaml
spec:
  # Every 15 minutes
  schedule: "*/15 * * * *"
  
  # Or other options:
  # schedule: "*/5 * * * *"   # Every 5 minutes
  # schedule: "0 * * * *"     # Every hour
  # schedule: "0 */6 * * *"   # Every 6 hours
```

### Manual Updates

Trigger an immediate update without waiting for CronJob:

```bash
# Create a one-time job from the CronJob template
kubectl create job -n gentian-server \
  --from=cronjob/odoo-modules-updater \
  manual-update-$(date +%s)

# Watch the job
kubectl get jobs -n gentian-server -w

# View logs
kubectl logs -n gentian-server -l app=odoo-modules-updater --tail=100
```

### Using Different Branches per Profile

You can configure different branches for different profiles:

**Gentian Profile** (`profiles/gentian/modules-git-config.yaml`):
```yaml
data:
  BRANCH: "main"
```

**Commune Profile** (`profiles/commune/modules-git-config.yaml`):
```yaml
data:
  BRANCH: "commune-modules"
```

Then update the CronJob to use the ConfigMap (requires patching).

## Private Repositories

If your module repository is private, add credentials:

### Option 1: HTTPS with Token

Create a secret:
```bash
kubectl create secret generic git-credentials \
  -n gentian-server \
  --from-literal=username=your-github-username \
  --from-literal=password=your-github-token
```

Update CronJob to use credentials:
```yaml
env:
- name: GIT_USERNAME
  valueFrom:
    secretKeyRef:
      name: git-credentials
      key: username
- name: GIT_PASSWORD
  valueFrom:
    secretKeyRef:
      name: git-credentials
      key: password
command:
- sh
- -c
- |
  REPO_URL="https://${GIT_USERNAME}:${GIT_PASSWORD}@github.com/gentian-org/odoo-modules.git"
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$TARGET_DIR"
```

### Option 2: SSH Keys

Create a secret with SSH key:
```bash
kubectl create secret generic git-ssh-key \
  -n gentian-server \
  --from-file=ssh-privatekey=/path/to/private-key
```

Mount and use in CronJob:
```yaml
volumeMounts:
- name: ssh-key
  mountPath: /root/.ssh
  readOnly: true
volumes:
- name: ssh-key
  secret:
    secretName: git-ssh-key
    defaultMode: 0400
```

## CI/CD Integration

For instant updates on git push, integrate with CI/CD:

### GitHub Actions Example

Create `.github/workflows/update-k8s-modules.yaml` in your modules repo:

```yaml
name: Update Kubernetes Modules

on:
  push:
    branches:
      - main

jobs:
  trigger-update:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger Kubernetes Job
        run: |
          kubectl create job \
            --from=cronjob/odoo-modules-updater \
            ci-update-${{ github.sha }} \
            --namespace=gentian-server
        env:
          KUBECONFIG: ${{ secrets.KUBECONFIG }}
```

This triggers an immediate update job whenever you push to the modules repository.

## Monitoring

Check module update status:

```bash
# View CronJob schedule and status
kubectl get cronjob -n gentian-server odoo-modules-updater

# List recent update jobs
kubectl get jobs -n gentian-server -l app=odoo-modules-updater

# View logs from last update
kubectl logs -n gentian-server \
  $(kubectl get pods -n gentian-server -l app=odoo-modules-updater --sort-by=.metadata.creationTimestamp -o name | tail -1)

# Count modules in PVC
kubectl exec -n gentian-server deployment/odoo -- \
  sh -c "find /opt/odoo/custom-addons -name '__manifest__.py' -o -name '__openerp__.py' | wc -l"

# List module names
kubectl exec -n gentian-server deployment/odoo -- \
  sh -c "find /opt/odoo/custom-addons -name '__manifest__.py' -o -name '__openerp__.py' | xargs dirname | xargs -n1 basename"
```

## Troubleshooting

### Modules not updating

1. Check CronJob is running:
   ```bash
   kubectl get cronjob -n gentian-server
   ```

2. Check recent jobs:
   ```bash
   kubectl get jobs -n gentian-server -l app=odoo-modules-updater
   ```

3. View job logs:
   ```bash
   kubectl logs -n gentian-server job/odoo-modules-updater-<timestamp>
   ```

4. Manually trigger update:
   ```bash
   kubectl create job -n gentian-server --from=cronjob/odoo-modules-updater test-update
   ```

### Permission errors

Ensure PVC has correct permissions:
```bash
# On Kubernetes node
sudo chown -R 999:999 /data/odoo-modules
sudo chmod -R 755 /data/odoo-modules
```

### Git authentication fails

Check secret exists:
```bash
kubectl get secret -n gentian-server git-credentials
```

Test with a one-off pod:
```bash
kubectl run -it --rm git-test \
  --image=alpine/git \
  --namespace=gentian-server \
  -- clone https://github.com/gentian-org/odoo-modules.git /tmp/test
```

## Best Practices

1. **Use branches/tags**: Pin production to stable tags, dev to main
2. **Test modules locally**: Use dev environment before pushing to production
3. **Monitor updates**: Set up alerts for failed CronJob executions
4. **Version your modules**: Tag releases in git for rollback capability
5. **Document dependencies**: Keep module dependencies clear in git README
