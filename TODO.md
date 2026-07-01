# K8s Factory MCP — What's included & what's next

A community reference for everyone using, testing, or contributing to this
project. Covers everything currently implemented, known gaps, and ideas for
future development. Pull requests welcome.

---

## ✅ What's implemented (k8s-mcp-v1)

### Core cluster lifecycle

| Feature | Tool | Notes |
|---------|------|-------|
| Cluster config validation | `plan_cluster` | Validates CNI, profile, monitoring, proxy, node_config; surfaces defaults before anything runs |
| OS auto-detection per node | `prepare_nodes` | SSH-detects Ubuntu/Debian, RHEL/CentOS/Rocky/Alma, SUSE — nodes in the same cluster can run different OSes |
| Multi-master HA | `bootstrap_cluster` | `--upload-certs` + `--control-plane` join for masters 2+; auto-detected from config |
| Worker bootstrap | `bootstrap_cluster` | `kubeadm join` runs in parallel across all workers |
| Parallel SSH everywhere | all multi-node tools | `ThreadPoolExecutor` used for prep, diagnostics, cert rotation, destroy |
| Cluster health check | `cluster_status` | Nodes, system pods, unhealthy pods, PVs, LoadBalancer services |
| Full cluster teardown | `destroy_cluster` | Parallel `kubeadm reset` + iptables flush; requires `confirm: DESTROY` |

### Node preparation

| Feature | Config key | Options |
|---------|-----------|---------|
| Swap handling | `node_config.swap` | `disable` (permanent), `warn` (runtime only), `keep` |
| SELinux mode (RHEL) | `node_config.selinux` | `permissive`, `enforcing`, `disabled` |
| Kernel modules | `node_config.kernel_modules` | `required`, `ipvs`, `ipvs_legacy`, `ebpf_extra`, `none` |
| Extra modules | `node_config.extra_modules` | Any list of module names |
| sysctl preset | `node_config.sysctl_preset` | `k8s-minimal` (3 params), `k8s-production` (14 params), `k8s-highperf` (20 params), `custom` |
| Custom sysctl overrides | `node_config.sysctl_custom` | Any `{param: value}` dict merged on top of preset |
| iptables mode | `node_config.iptables_mode` | `auto`, `legacy`, `nftables` |
| Transparent hugepages | `node_config.hugepages` | `true` (leave THP on), `false` (disable — default) |
| System ulimits | `node_config.ulimits` | `true` (write `/etc/security/limits.d/99-k8s.conf`), `false` |
| containerd SystemdCgroup | automatic | Always set to `true` in generated config |
| containerd proxy drop-in | `proxy` block | Writes systemd drop-in so daemon inherits proxy |

### Networking (CNI)

| CNI | Install method | Special options |
|-----|---------------|-----------------|
| Cilium | Helm | eBPF, kube-proxy replacement, Hubble UI, Hubble relay — all on by default |
| Calico | Helm (Tigera operator) | BGP-capable |
| Flannel | kubectl apply | VXLAN overlay |
| Weave | kubectl apply | Mesh networking |
| CNI override values | `cni_options` in config | Any Helm `--set` key passed through |

### Package stack profiles

| Profile | What gets installed |
|---------|---------------------|
| `production` | ArgoCD, cert-manager, ingress-nginx, MetalLB, Velero |
| `development` | ArgoCD, ingress-nginx, cert-manager, Kubernetes Dashboard |
| `ml-gpu` | NVIDIA GPU Operator, Argo Workflows, Kubeflow Training Operator |
| `edge` | MetalLB, Longhorn |
| `multi-tenant` | ArgoCD, cert-manager, ingress-nginx, Capsule (namespace isolation) |

### Monitoring

| Option | Stack |
|--------|-------|
| `prometheus` | kube-prometheus-stack: Prometheus + Grafana + Alertmanager |
| `prometheus-loki` | Above + Loki + Promtail for log aggregation |
| `none` | Skip |

### CI/CD

| Feature | Tool | Notes |
|---------|------|-------|
| Jenkins-in-cluster | `install_jenkins` | ClusterIP-only, persistent volume, Kubernetes plugin pre-installed |
| In-cluster build agents | automatic | Jenkins Kubernetes plugin lets it spawn build pods in the same cluster |

### Storage

| StorageClass | Install method | Notes |
|-------------|---------------|-------|
| Longhorn | Helm | Distributed block storage, replicated |
| NFS subdir | Helm | Needs `nfs_server` + `nfs_path` in config |
| Local-path | kubectl apply | Rancher local-path provisioner |
| Rook-Ceph | Helm | Full Ceph storage via Rook operator |
| Set as default | `set_default: true` | Patches the StorageClass annotation automatically |

### Cluster scaling & upgrades

| Feature | Tool | Notes |
|---------|------|-------|
| Add worker nodes | `scale_cluster` (action: add) | Auto-detects OS, preps, and joins in parallel |
| Add master nodes (HA) | `scale_cluster` (action: add, role: master) | Uses certificate key for control-plane join |
| Drain node | `scale_cluster` (action: drain) | `--ignore-daemonsets --delete-emptydir-data --force` |
| Remove node | `scale_cluster` (action: remove) | Drain + `kubectl delete node` |
| Rolling K8s upgrade | `upgrade_cluster` | OS-aware per node; masters serial, workers in parallel batches |
| Batch size for workers | `worker_batch_size` | Default 3 workers upgraded in parallel per batch |

### Backup and recovery

| Feature | Tool | Notes |
|---------|------|-------|
| etcd snapshot | `backup_etcd` | Timestamped, uses cluster PKI certs |
| etcd restore | `restore_etcd` | Stops control plane, restores, restarts; requires `confirm: RESTORE` |
| Full resource dump | `cluster_snapshot` | All non-secret K8s resources to YAML on master node |

### Access control

| Feature | Tool | Notes |
|---------|------|-------|
| Scoped kubeconfig | `manage_kubeconfig` | ServiceAccount + RoleBinding + 1-year token; roles: view, edit, admin |
| Namespace + quotas + RBAC | `provision_namespace` | ResourceQuota + LimitRange + RoleBinding in one shot |

### Certificates

| Feature | Tool | Notes |
|---------|------|-------|
| Check cert expiry | `rotate_certs` (check_only: true) | Runs on all masters in parallel |
| Renew all certs | `rotate_certs` | Parallel across all masters, restarts kubelet |

### Observability

| Feature | Tool | Notes |
|---------|------|-------|
| Tail pod logs | `stream_logs` | By pod name, label selector, or namespace |
| Previous container logs | `stream_logs` (previous: true) | Post-crash log retrieval |
| Per-node diagnostics | `node_diagnostics` | Parallel; disk, memory, CPU, kernel, kubelet logs, OOM events, OS info |
| Security audit | `audit_cluster` | Privileged pods, root-user containers, missing limits, NodePort services, RBAC, unbound PVCs, cert expiry |

### Helm management

| Feature | Tool / action | Notes |
|---------|--------------|-------|
| List releases | `helm_manage` (list) | All namespaces or scoped |
| Release status | `helm_manage` (status) | |
| Release history | `helm_manage` (history) | |
| Upgrade release | `helm_manage` (upgrade) | Proxy-aware |
| Rollback release | `helm_manage` (rollback) | By revision number |
| Uninstall release | `helm_manage` (uninstall) | |

### Workload migration

| Feature | Tool | Notes |
|---------|------|-------|
| docker-compose → K8s | `migrate_workload` | Deployment + Service + env vars + probes per service |
| systemd unit → K8s | `migrate_workload` | Best-effort ExecStart parse |
| HPA generation | `migrate_workload` (add_hpa: true) | CPU-based autoscaling |
| PDB generation | `migrate_workload` (add_pdb: true) | minAvailable: 1 |
| Volume hints | automatic | Flags docker-compose volumes and suggests PVCs |

### Proxy support

| Scope | How applied |
|-------|-------------|
| Shell env | `export http_proxy / https_proxy / no_proxy` |
| apt (Debian) | `/etc/apt/apt.conf.d/95proxies` |
| dnf/yum (RHEL) | Appended to `/etc/dnf/dnf.conf` or `/etc/yum.conf` |
| containerd | systemd drop-in `/etc/systemd/system/containerd.service.d/http-proxy.conf` |
| helm | Shell env (helm reads it natively) |
| kubectl apply -f url | Shell env |
| upgrade and scale | Re-applied on every package operation |

### OS support

| OS family | Package manager | Tested distros |
|-----------|----------------|---------------|
| `debian` | apt | Ubuntu 20.04+, Debian 10+ |
| `rhel` | dnf / yum | RHEL 8+, CentOS Stream 8+, Rocky Linux 8+, AlmaLinux 8+ |
| `suse` | zypper | SLES 15+, openSUSE Leap 15+ |
| Mixed clusters | per-node detection | Each node detected independently — master can be RHEL, workers Ubuntu |

### Guided UX

| Feature | Notes |
|---------|-------|
| Next-step menus | Every successful tool call returns a numbered menu of contextual next actions |
| plan_cluster prompting | Asks for CNI, profile, monitoring, proxy if not specified rather than guessing |
| Dry-run mode | Every mutating tool supports `dry_run: true`; `global_dry_run: true` in config applies to all tools |
| Config validation | All required fields, supported values, and node_config options validated before anything touches nodes |
| node_config summary | `plan_cluster` always shows what kernel/sysctl/iptables/SELinux/swap settings will be applied |

### Session persistence and multi-cluster

| Feature | Tool / mechanism | Notes |
|---------|-----------------|-------|
| Auto session save | `done()` helper | State saved to `~/.k8s-mcp/state.json` after every successful tool call |
| Session auto-restore | Module startup | `_load_state()` runs at import — state restored from disk on every terminal open |
| Named cluster sessions | `save_cluster` | Save current session under a human-readable name |
| Multi-cluster switching | `switch_cluster` | Load any saved session as the active one; all tools follow |
| Cluster listing | `list_clusters` | Shows all saved clusters with versions, node counts, and installed packages |
| Session cleanup | `delete_cluster` | Remove a named session from registry (does not destroy actual cluster) |
| State file location | `~/.k8s-mcp/state.json` | `chmod 600`, JSON format |
| Clusters registry location | `~/.k8s-mcp/clusters.json` | `chmod 600`, JSON format |

### Audit trail

| Feature | Tool / mechanism | Notes |
|---------|-----------------|-------|
| Per-call audit logging | `_audit()` called on every `call_tool` entry | Logs tool name, cluster, parameters, outcome |
| Secret masking | Automatic in `_audit()` | Passwords, tokens, keys replaced with `***` before writing |
| Audit log viewer | `show_audit_log` | Filterable by cluster name and tool name |
| Audit log location | `~/.k8s-mcp/audit.log` | `chmod 600`, JSON lines format |

### Reliability and safety

| Feature | Tool / behaviour | Notes |
|---------|-----------------|-------|
| `bootstrap_cluster` idempotency | Pre-checks `/etc/kubernetes/admin.conf` | Skips `kubeadm init` if master already initialized; regenerates fresh join token and cert key instead |
| Certificate key TTL auto-regeneration | Inside `bootstrap_cluster` | Cert keys expire after 2 hours; always regenerated fresh on HA master joins |
| `install_stack` resume-from-failure | Tracks `_state["stack_installed"]` | Re-run after failure skips already-installed releases, retries only failed ones |
| CIDR overlap detection | `plan_cluster` + `validate_config` | `pod_cidr` and `service_cidr` checked for overlap using Python `ipaddress` module |
| Node name uniqueness | `plan_cluster` + `validate_config` | Duplicate node names caught before SSH is attempted |
| SSH key existence check | `validate_config` | Warns if SSH key files don't exist on the local machine |
| K8s version format check | `validate_config` | Enforces `MAJOR.MINOR` format before any install |
| Credential rotation warning | `generate_cluster_report` | Always shows which credentials to rotate and how, plus instructions not to commit to git |
| Global dry-run mode | `global_dry_run: true` in config | Applies dry-run to every tool in the session without per-tool flags |

### Offline validation

| Feature | Tool | Notes |
|---------|------|-------|
| Offline config validation | `validate_config` | Validates CIDR, field presence, node names, SSH keys, K8s version format — no SSH required |

### Preflight checks

| Feature | Tool | Notes |
|---------|------|-------|
| Pre-bootstrap node check | `preflight_check` | Checks disk, RAM, ports, swap, internet, and all required tools in parallel across nodes |
| Auto-fix missing tools | `preflight_check` (fix: true) | Installs Helm, etcdctl, git, jq automatically if missing |

### Repository files

| File | Description |
|------|-------------|
| `examples/single-node-dev.yaml` | Single-node dev cluster — minimum hardware, flannel CNI |
| `examples/3-node-production.yaml` | Standard production: 1 master + 2 workers, Cilium |
| `examples/5-node-ha.yaml` | HA: 3 masters + 2 workers, supports mixed OS |
| `examples/openstack-rhel-proxy.yaml` | OpenStack RHEL 8 with corporate proxy — tested config |
| `examples/gpu-ml-cluster.yaml` | GPU workers, ml-gpu profile, highperf sysctl |
| `CONTRIBUTING.md` | How to add tools, OS support, compliance checks, example configs |
| `LICENSE` | Apache 2.0 |

---

## 🔲 To-do / known gaps

### High priority — commonly needed by learners / testers

- [ ] **Air-gapped / offline install mode** — pull all container images and Helm charts to a local registry first, then install without any internet access. Needs a `registry_mirror` config block and preflight image-pull step before `prepare_nodes`.
- [ ] **kube-vip for HA VIP** — currently multi-master HA has no shared VIP. Adding a `control_plane_vip` field and running kube-vip as a static pod on each master would give true HA without an external load balancer.
- [ ] **kubeconfig download to local machine** — after `bootstrap_cluster`, offer to write the kubeconfig to a local path on the machine running the MCP server, not just store it in session state.
- [ ] **Cluster health pre-flight check** — before `prepare_nodes` runs, verify all nodes are reachable over SSH, have enough disk space (>= 20 GB free), have enough memory (>= 2 GB), and the correct ports aren't already in use.
- [ ] **Node taint and label configuration** — allow `masters` and `workers` entries to specify `taints` and `labels` in the config, applied after the node joins.
- [ ] **Multiple control-plane endpoints** — support `control_plane_endpoint` as a separate config field pointing at a VIP or external load balancer, distinct from the first master's IP.

### Medium priority — production hardening

- ✅ **Pod security admission** — implemented as `configure_pod_security` tool (baseline/restricted per namespace).
- ✅ **NetworkPolicy default-deny** — implemented inside `configure_pod_security` (default_deny_network: true).
- ✅ **etcd encryption at rest** — implemented as `configure_etcd_encryption` (AES-CBC or AES-GCM).
- ✅ **Audit logging** — implemented as `configure_audit_logging` (API server) + `~/.k8s-mcp/audit.log` (MCP level).
- [ ] **Node draining timeout config** — `scale_cluster` drain uses a fixed timeout; make it configurable.
- [ ] **Cluster backup scheduling** — `backup_etcd` is manual; add a `schedule_backup` tool writing a CronJob.
- [ ] **Multi-etcd external cluster** — etcd is stacked (on master nodes). Support external etcd topology for very large HA clusters.

### Lower priority — nice to have

- [ ] **GPU node labelling** — after joining a GPU worker, automatically add `nvidia.com/gpu=true` label.
- [ ] **Istio service mesh** — add Istio to the supported `install_stack` profiles (complex enough to warrant its own tool).
- ✅ **OIDC / SSO integration** — implemented as `install_applications` with Keycloak, which wires kube-apiserver OIDC flags automatically.
- ✅ **Cluster cost reporting** — implemented as `cost_report` tool with per-namespace breakdown and cloud/on-prem rates.
- [ ] **Windows worker nodes** — Windows container support needs a separate prep script branch.
- [ ] **ARM64 / mixed-arch clusters** — prep scripts use same binary names; test and document ARM64 explicitly.
- [ ] **Automatic cert renewal CronJob** — write a CronJob that calls `kubeadm certs renew all` 30 days before expiry.

### Repo / community infrastructure

- [ ] **GitHub Actions CI** — lint the Python file on push, run `python3 -W error -c "import ast; ast.parse(...)"` as a check.
- [ ] **Test fixtures with kind** — a `tests/` directory that spins up a local `kind` cluster and smoke-tests each MCP tool against it (no real VMs needed for CI).
- ✅ **Example configs directory** — `examples/` folder with 5 configs: single-node-dev, 3-node-production, 5-node-ha, openstack-rhel-proxy, gpu-ml-cluster.
- ✅ **Contributing guide** — `CONTRIBUTING.md` covering how to add tools, OS support, compliance checks, and example configs.
- [ ] **Changelog** — `CHANGELOG.md` tracking what changes between releases. Start from k8s-mcp-v1.
- ✅ **License file** — `LICENSE` (Apache 2.0).

---

## Release

| Release | Tools | Description |
|---------|-------|-------------|
| k8s-mcp-v1 | 41 | Initial public release — full cluster lifecycle, OS-aware, HA, proxy, security, applications, compliance, cost reporting, cluster report, session persistence, multi-cluster management, audit trail, offline validation, idempotent bootstrap, resume-from-failure install |

---

## How to contribute

1. Fork the repo
2. Add your feature or fix — new tools go in the `call_tool` handler, new config options go in the constants section at the top
3. Run `python3 -W error -c "import ast; ast.parse(open('k8s_factory_mcp.py').read())"` to verify syntax
4. Update `TODO.md` — move your item from To-do to What's included
5. Add an example config to `examples/` if relevant
6. Open a pull request with a short description of what it does and which to-do item it addresses
