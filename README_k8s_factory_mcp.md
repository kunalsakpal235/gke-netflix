# K8s Cluster Factory MCP — v3

A custom MCP server that provisions, scales, upgrades, monitors, and runs CI/CD on
**bare-metal / on-premises Kubernetes clusters** from a single YAML config — across
mixed operating systems, with multi-master HA support.

---

## What's new in v3.1

- **Corporate proxy support.** A top-level `proxy` block in the config
  (`http_proxy`, `https_proxy`, `no_proxy`) is applied automatically to every
  network-touching command across the entire cluster lifecycle: apt/dnf/zypper
  package installs, containerd (via its own systemd drop-in — daemons don't
  inherit SSH shell env vars), curl-based repo key fetches, `helm repo add` /
  `helm upgrade`, and `kubectl apply -f <url>`. Set it once at `plan_cluster`
  time and every subsequent tool (`prepare_nodes`, `install_cni`, `install_stack`,
  `install_monitoring`, `install_jenkins`, `provision_storage`, `upgrade_cluster`,
  `scale_cluster`, `helm_manage`) honors it without any extra flags. No proxy
  block configured = zero overhead, scripts run exactly as before.

## What's new in v3.0

- **OS-independent.** Every node's OS is auto-detected over SSH (Ubuntu/Debian,
  RHEL/CentOS/Rocky/Alma, or SUSE) and the matching package manager (apt/dnf/yum/zypper)
  is used automatically. Nodes in the same cluster can run different OSes. You can also
  set `os_family` explicitly per node in the config to skip detection.
- **True multi-master HA.** List 2+ entries under `masters` in the config and the
  cluster bootstraps with `kubeadm init --upload-certs` plus `kubeadm join --control-plane`
  for the additional masters automatically.
- **SSH concurrency everywhere.** `prepare_nodes`, `destroy_cluster`, `node_diagnostics`,
  `rotate_certs`, and the worker phase of `upgrade_cluster` all run in parallel
  (batched for upgrades) instead of one node at a time.
- **`install_monitoring`** — dedicated tool for kube-prometheus-stack alone, or
  + Loki/Promtail for log aggregation. Selectable per cluster.
- **`install_jenkins`** — Jenkins inside the cluster via Helm, ClusterIP-only,
  persistent volume, Kubernetes plugin pre-installed so Jenkins can launch its own
  build agents as pods in the same cluster.

---

## All 23 tools

| Tool | What it does |
|------|-------------|
| `plan_cluster` | Validates config (incl. HA, OS, monitoring), returns plan |
| `prepare_nodes` | Auto-detects OS per node, installs containerd/kubeadm in parallel |
| `bootstrap_cluster` | kubeadm init, HA control-plane joins, worker joins |
| `install_cni` | Cilium / Calico / Flannel / Weave |
| `install_stack` | Helm packages for the use-case profile |
| `install_monitoring` | kube-prometheus-stack, optionally + Loki |
| `install_jenkins` | Jenkins-in-cluster, ClusterIP-only |
| `cluster_status` | Node/pod/PV/LB health check |
| `destroy_cluster` | Parallel kubeadm reset across all nodes |
| `scale_cluster` | Add/drain/remove workers OR masters, OS-aware |
| `upgrade_cluster` | Rolling upgrade, OS-aware, batched parallel workers |
| `backup_etcd` / `restore_etcd` | Snapshot and disaster recovery |
| `rotate_certs` | Check/renew certs on every master in parallel |
| `manage_kubeconfig` | Scoped kubeconfig generation |
| `provision_namespace` | Namespace + quota + RBAC in one shot |
| `provision_storage` | Longhorn / NFS / local-path / Rook-Ceph |
| `migrate_workload` | docker-compose / systemd \u2192 K8s manifests |
| `stream_logs` | Tail pod logs |
| `audit_cluster` | Security/config sweep |
| `node_diagnostics` | Per-node deep diagnostics, parallel, includes OS info |
| `helm_manage` | List/status/upgrade/rollback/uninstall any release |
| `cluster_snapshot` | Dump all resources to YAML for GitOps/DR |

---

## Install

```bash
pip install mcp paramiko pyyaml --break-system-packages
```

---

## Wire into Claude Code

```bash
mkdir -p ~/mcp-servers
cp k8s_factory_mcp.py ~/mcp-servers/k8s_factory_mcp.py
claude mcp add k8s-factory -- python3 ~/mcp-servers/k8s_factory_mcp.py
claude mcp list
```

---

## Config — mixed OS, multi-master HA example

```yaml
cluster_name: prod-cluster
k8s_version: "1.30"
cni: cilium
pod_cidr: "10.244.0.0/16"
service_cidr: "10.96.0.0/12"
profile: production
monitoring: prometheus-loki      # prometheus | prometheus-loki | none

masters:
  - name: master-1
    ip: 10.0.0.10
    user: ubuntu
    ssh_key: ~/.ssh/id_rsa
    # os_family omitted -> auto-detected
  - name: master-2
    ip: 10.0.0.11
    user: ubuntu
    ssh_key: ~/.ssh/id_rsa
  - name: master-3
    ip: 10.0.0.12
    user: centos
    ssh_key: ~/.ssh/id_rsa
    os_family: rhel              # explicit override skips detection

workers:
  - name: worker-1
    ip: 10.0.0.20
    user: ubuntu
    ssh_key: ~/.ssh/id_rsa
  - name: worker-2
    ip: 10.0.0.21
    user: ubuntu
    ssh_key: ~/.ssh/id_rsa
```

3 masters \u2192 HA mode automatically. `os_family` per node is optional; omit it
and `prepare_nodes` detects Ubuntu/Debian vs RHEL-family vs SUSE itself.

---

## Config — behind a corporate proxy

```yaml
cluster_name: corp-cluster
k8s_version: "1.30"
cni: cilium
pod_cidr: "10.244.0.0/16"
service_cidr: "10.96.0.0/12"
profile: production

proxy:
  http_proxy:  "http://proxy.corp.local:3128"
  https_proxy: "http://proxy.corp.local:3128"
  no_proxy:    "localhost,127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.svc,.cluster.local,.corp.local"

masters:
  - name: master-1
    ip: 10.0.0.10
    user: ubuntu
    ssh_key: ~/.ssh/id_rsa
workers:
  - name: worker-1
    ip: 10.0.0.20
    user: ubuntu
    ssh_key: ~/.ssh/id_rsa
```

Once `proxy` is set, every subsequent tool call in the session reads it from
the stored cluster config automatically \u2014 you never pass proxy settings to
individual tools. `plan_cluster` will warn you if no proxy block is present
at all, in case your org needs one and it was simply forgotten.

---

## Usage flow

```
You:  Plan this cluster: [paste config]
Claude: -> plan_cluster -> shows plan, notes HA mode and OS auto-detection

You:  Prepare the nodes.
Claude: -> prepare_nodes -> detects each node's OS in parallel, then installs
           containerd/kubeadm with the matching package manager per node

You:  Bootstrap it.
Claude: -> bootstrap_cluster -> kubeadm init on master-1, HA-joins master-2 and
           master-3 as control-plane nodes, joins all workers in parallel

You:  Install Cilium, then the production stack.
Claude: -> install_cni -> install_stack

You:  Set up monitoring with Prometheus and Loki.
Claude: -> install_monitoring (monitoring_type: prometheus-loki)

You:  Set up Jenkins for CI/CD.
Claude: -> install_jenkins -> ClusterIP service, ready for in-cluster pipelines

You:  Check cluster health.
Claude: -> cluster_status
```

---

## Monitoring access

```bash
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80
# admin / admin-changeme (or whatever grafana_password you set)
```

## Jenkins access

```bash
kubectl port-forward -n jenkins svc/jenkins 8080:8080
# admin / admin-changeme (or whatever admin_password you set)
```

Jenkins ships with the Kubernetes plugin pre-installed, so it can launch build
agents as pods directly in this same cluster using its own in-cluster
ServiceAccount \u2014 no extra credentials needed to wire that up.

---

## Multi-master HA notes

- `bootstrap_cluster` automatically detects HA mode from `len(masters) > 1` in
  your config and uses `--upload-certs` + the certificate key for control-plane joins.
- `upgrade_cluster` upgrades the first master, then additional masters one at a
  time (serial \u2014 each needs the previous stable), then workers in parallel batches.
- `rotate_certs` renews certificates on every master concurrently.
- `restore_etcd` on an HA cluster prints a warning: a single-master restore can
  desync etcd across masters in production. Stop etcd cluster-wide before restoring.

---

## Security notes

- SSH keys never leave your machine \u2014 read locally by paramiko.
- `destroy_cluster` requires explicit `confirm: DESTROY`.
- `restore_etcd` requires explicit `confirm: RESTORE`.
- Change the default Grafana/Jenkins passwords (`admin-changeme`) before any
  real use \u2014 pass `grafana_password` / `admin_password` explicitly.

