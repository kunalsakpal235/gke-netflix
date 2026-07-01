# k8s-mcp-v1 — Kubernetes Cluster Factory MCP

> **Version:** k8s-mcp-v1  
> **Tools:** 34  
> **Lines of code:** ~3,300  
> **Tested on:** RHEL 8+, Ubuntu 20.04+, CentOS Stream 8+, Rocky Linux 8+, AlmaLinux 8+, SUSE 15+  
> **Works on:** Any on-premises bare metal, OpenStack, VMware, AWS, GCP, Azure  

---

## Table of contents

1. [What this is](#1-what-this-is)
2. [What is MCP?](#2-what-is-mcp)
3. [What is Kubernetes?](#3-what-is-kubernetes)
4. [Why this exists](#4-why-this-exists)
5. [How it works — the big picture](#5-how-it-works--the-big-picture)
6. [Prerequisites](#6-prerequisites)
7. [Installation](#7-installation)
8. [Cluster config file — every field explained](#8-cluster-config-file--every-field-explained)
9. [All 41 tools — complete reference](#9-all-41-tools--complete-reference)
10. [Cluster profiles](#10-cluster-profiles)
11. [CNI options](#11-cni-options)
12. [Node configuration — kernel, sysctl, iptables, SELinux](#12-node-configuration--kernel-sysctl-iptables-selinux)
13. [Security layer](#13-security-layer)
14. [Applications](#14-applications)
15. [Certificates](#15-certificates)
16. [Monitoring](#16-monitoring)
17. [Cost reporting](#17-cost-reporting)
18. [Cluster report output files](#18-cluster-report-output-files)
19. [Operating systems supported](#19-operating-systems-supported)
20. [Corporate proxy support](#20-corporate-proxy-support)
21. [Multi-master HA](#21-multi-master-ha)
22. [Workflow walkthrough — zero to running cluster](#22-workflow-walkthrough--zero-to-running-cluster)
23. [Compliance standards](#23-compliance-standards)
24. [Troubleshooting](#24-troubleshooting)
25. [Contributing](#25-contributing)
26. [Glossary](#26-glossary)
27. [Setting up the executor node — step by step](#27-setting-up-the-executor-node--step-by-step)
28. [Example prompts — how to talk to Claude](#28-example-prompts--how-to-talk-to-claude)

**Quick reference:** [Session persistence](#how-session-state-works) | [Multi-cluster](#save_cluster) | [Audit trail](#show_audit_log) | [Offline validation](#validate_config) | [Examples directory](#repo-structure)

---

## 1. What this is

`k8s-mcp-v1` is a single Python file (`k8s_factory_mcp.py`) that turns Claude AI into a full Kubernetes cluster operator. Instead of running `kubectl`, `kubeadm`, `helm`, or SSH commands manually, you have a conversation with Claude and it does all of that for you — on real infrastructure.

You describe what you want. Claude calls the right tools in the right order. Your nodes get a Kubernetes cluster.

**What it can do:**
- Provision a Kubernetes cluster from scratch on any Linux servers (on-prem, OpenStack, or cloud VMs)
- Auto-detect the OS on each node and use the right package manager (apt / dnf / yum / zypper)
- Set up multi-master HA with a single config change
- Install monitoring (Prometheus + Grafana + Loki), CI/CD (Jenkins), a container registry (Harbor), secrets management (Vault), SSO (Keycloak), and code quality scanning (SonarQube)
- Run compliance audits against CIS, NSA/CISA, PCI-DSS, and SOC2/ISO27001 standards
- Rotate certificates with zero downtime
- Generate a complete cluster report (credentials, IPs, namespaces, costs) as Markdown and YAML
- Estimate cluster running costs for on-prem, OpenStack, AWS, GCP, and Azure
- Manage multiple named cluster sessions — switch between prod/staging/dev without losing context
- Keep a full audit trail of every action taken (timestamped, secrets masked, compliance-ready)
- Validate configs completely offline before touching any server

**What it does NOT do:**
- Provision the virtual machines themselves (you need existing Linux VMs with SSH access)
- Manage DNS or load balancers outside the cluster
- Store any credentials itself — they are written to files on your master node

**Repo structure:**
```
k8s_factory_mcp.py         — 41 tools, ~4,100 lines, the entire MCP server
cluster_config.yaml         — fully annotated reference configuration
README.md                   — complete documentation (28 sections)
TODO.md                     — feature matrix and roadmap
CONTRIBUTING.md             — how to add tools, OS support, compliance checks
LICENSE                     — Apache 2.0
examples/
  single-node-dev.yaml      — single VM for learning
  3-node-production.yaml    — standard production cluster
  5-node-ha.yaml            — 3 masters + 2 workers, HA
  openstack-rhel-proxy.yaml — OpenStack RHEL behind a corporate proxy
  gpu-ml-cluster.yaml       — GPU workers + ML profile
```

---

## 2. What is MCP?

MCP stands for **Model Context Protocol**. It is an open standard created by Anthropic that lets Claude AI connect directly to external tools and services — not just talk about them, but actually call them.

Before MCP, you would describe a problem to Claude, get a script back, and run it yourself. With MCP, Claude runs the script for you on your actual infrastructure.

**How MCP works in this project:**

```
You (in the claude terminal)
       │
       ▼
Claude AI  ──── reads your message ────► decides which tool to call
       │
       ▼
k8s_factory_mcp.py  ──── SSHes into your servers ────► runs the actual commands
       │
       ▼
Your servers get configured
```

The file `k8s_factory_mcp.py` is the MCP server. It runs locally on whichever machine has SSH access to your nodes. Claude calls it through a protocol over standard I/O — you never interact with the Python file directly.

**Why MCP for infrastructure?**
- You can investigate problems conversationally: ask a follow-up, drill down, pivot to a different system
- Context is maintained across calls: when you say "add another worker", it already knows your cluster config
- Every tool has a dry-run mode so you can see what would happen before it does

---

## 3. What is Kubernetes?

Kubernetes (often abbreviated K8s) is an open-source system for running containerized applications across multiple machines. Instead of deploying an application to a specific server, you describe the desired state ("I want 3 copies of this container running") and Kubernetes figures out where to run them and keeps them running.

**Key concepts you will encounter in this project:**

| Term | What it means |
|------|--------------|
| **Node** | A Linux server that is part of the cluster |
| **Master node** | The server that runs the Kubernetes control plane (API server, scheduler, etcd) |
| **Worker node** | A server that runs your application containers |
| **Pod** | The smallest deployable unit — one or more containers running together |
| **Namespace** | A logical partition inside the cluster — like a folder for related resources |
| **CNI** | Container Network Interface — the plugin that gives pods their IP addresses and network connectivity |
| **Helm** | A package manager for Kubernetes — like apt/yum but for K8s applications |
| **kubeadm** | The official tool for bootstrapping a Kubernetes cluster |
| **etcd** | The key-value store that holds all cluster state |
| **StorageClass** | Defines how persistent storage is provisioned for pods |
| **RBAC** | Role-Based Access Control — who can do what in the cluster |
| **ServiceAccount** | An identity for processes running inside pods |
| **kubeconfig** | A file that contains credentials and connection info for accessing a cluster |
| **ClusterIssuer** | A cert-manager resource that issues TLS certificates |

---

## 4. Why this exists

Setting up a production-grade Kubernetes cluster on bare metal or on-premises infrastructure is hard. The official documentation covers the happy path. Real infrastructure has:

- Multiple Linux distributions across different nodes
- Corporate proxies that break every curl and apt-get
- SELinux that silently blocks things
- iptables vs nftables conflicts between kernel versions
- Security requirements (CIS benchmark, PCI-DSS, etcd encryption) that require dozens of separate steps
- No billing dashboard to tell you what is running and what it costs

This project encodes all of that operational knowledge into a single file. A junior engineer can follow the conversation flow. A senior engineer can customize every parameter. Security teams get compliance reports. Finance teams get cost estimates.

---

## 5. How it works — the big picture

```
cluster_config.yaml          k8s_factory_mcp.py           Your Linux servers
      │                              │                            │
      │  plan_cluster(config)        │                            │
      ├─────────────────────────────►│                            │
      │                              │  validates, stores state   │
      │                              │                            │
      │  prepare_nodes()             │                            │
      ├─────────────────────────────►│  SSH ──────────────────────►
      │                              │  detect OS per node        │
      │                              │  install containerd        │
      │                              │  install kubeadm           │
      │                              │◄──────────────────────────┤
      │                              │                            │
      │  bootstrap_cluster()         │                            │
      ├─────────────────────────────►│  SSH ──────────────────────►
      │                              │  kubeadm init (master)     │
      │                              │  kubeadm join (workers)    │
      │                              │◄──────────────────────────┤
      │                              │                            │
      │  install_cni()               │                            │
      ├─────────────────────────────►│  helm install cilium       │
      │                              │                            │
      │  install_stack()             │                            │
      ├─────────────────────────────►│  helm install argocd       │
      │                              │  helm install prometheus   │
      │                              │  ...                       │
      │                              │                            │
      │  generate_cluster_report()   │                            │
      ├─────────────────────────────►│  collects all creds+IPs    │
      │  ◄── Markdown + YAML ────────│  writes to /opt/cluster-report/
```

The MCP server keeps the cluster config in memory for the entire session. You never need to re-specify IPs, SSH keys, or settings — they flow through automatically from `plan_cluster` to every subsequent tool.

---

## 6. Prerequisites

### On your control machine (where you run `claude`)

| Requirement | Why |
|-------------|-----|
| Python 3.10 or newer | The `mcp` package requires 3.10+. RHEL 8 default Python (3.6) is too old. |
| `pip install mcp paramiko pyyaml` | MCP SDK, SSH client, YAML parser |
| Claude Code CLI (`claude`) | The terminal interface to Claude. Install: `curl -fsSL https://claude.ai/install.sh | bash` |
| SSH key access to all nodes | The MCP server uses `paramiko` to SSH. Test manually: `ssh user@node-ip` before starting |

### On each cluster node (before you start)

| Requirement | Why |
|-------------|-----|
| Linux: RHEL 8+, Ubuntu 20.04+, Rocky/Alma 8+, CentOS Stream 8+, SUSE 15+ | Tested OS families |
| At least 2 vCPU, 2 GB RAM per worker | Kubernetes minimum; 4 vCPU / 8 GB recommended |
| At least 4 vCPU, 4 GB RAM per master | Control plane components are memory-hungry |
| 20 GB+ free disk on `/` | Container images, logs, etcd data |
| SSH accessible from the control machine | The MCP server SSHes into every node |
| Internet access (or corporate proxy configured) | To download packages and container images |
| All nodes must reach each other on their internal IPs | Kubernetes cluster networking requirement |

### Ports that must be open between nodes

| Port | Protocol | Used by |
|------|----------|---------|
| 6443 | TCP | Kubernetes API server |
| 2379–2380 | TCP | etcd client and peer communication |
| 10250 | TCP | kubelet API |
| 10251 | TCP | kube-scheduler |
| 10252 | TCP | kube-controller-manager |
| 30000–32767 | TCP | NodePort service range |
| All | All | Between nodes in the same cluster (for pod networking) |

---

## 7. Installation

### Step 1 — Install Python dependencies

```bash
pip install mcp paramiko pyyaml --break-system-packages
```

On RHEL 8 where stock Python is 3.6:
```bash
sudo dnf install -y python3.11 python3.11-pip
python3.11 -m pip install mcp paramiko pyyaml
```

### Step 2 — Install Claude Code

```bash
curl -fsSL https://claude.ai/install.sh | bash
claude --version
```

On first run, Claude Code will print an authentication URL. Open it in a browser and authenticate with your Anthropic account. The session token is stored locally.

### Step 3 — Save the MCP server

```bash
mkdir -p ~/mcp-servers
cp k8s_factory_mcp.py ~/mcp-servers/k8s_factory_mcp.py
```

### Step 4 — Register the MCP server with Claude Code

```bash
claude mcp add k8s-factory -- python3 ~/mcp-servers/k8s_factory_mcp.py
```

If you installed Python 3.11 alongside the system Python:
```bash
claude mcp add k8s-factory -- python3.11 ~/mcp-servers/k8s_factory_mcp.py
```

### Step 5 — Verify

```bash
claude mcp list
```

Output should show `k8s-factory` with status `connected`. If it shows `disconnected`, run the server directly to see why:

```bash
python3 ~/mcp-servers/k8s_factory_mcp.py
```

Common errors and fixes:

| Error | Fix |
|-------|-----|
| `No module named 'mcp'` | Run `pip install mcp` again; check you are using the same Python |
| `No module named 'paramiko'` | Run `pip install paramiko` |
| `disconnected` in mcp list | Run the server directly to see the actual import error |
| Permission denied on SSH | Check that `~/.ssh/id_rsa` exists and the public key is on the nodes |

### Step 6 — Start a session

```bash
claude
```

You are now talking to Claude with all 34 k8s-factory tools available. Type `/mcp` inside the session to confirm the tools are loaded.

---

## 8. Cluster config file — every field explained

All cluster settings live in a single YAML file that you paste into Claude when you say "plan this cluster". Here is the complete structure with every field documented.

```yaml
# ── Required fields ──────────────────────────────────────────────────────────

cluster_name: my-cluster          # Any string. Used in report filenames and labels.
k8s_version: "1.30"               # Kubernetes version. Format: "MAJOR.MINOR" (no patch).
                                  # Supported: 1.28, 1.29, 1.30, 1.31

cni: cilium                       # CNI plugin. Options: cilium | calico | flannel | weave
                                  # See section 11 for detailed comparison.

pod_cidr: "10.244.0.0/16"        # IP range for pods. Must NOT overlap with:
                                  #   - your node subnet
                                  #   - service_cidr
                                  #   - any other routed network on your infrastructure

service_cidr: "10.96.0.0/12"     # IP range for K8s Services (ClusterIP). Same overlap rules.

profile: production               # What Helm packages to install. Options:
                                  #   production    — ArgoCD, cert-manager, ingress-nginx, MetalLB, Velero
                                  #   development   — ArgoCD, ingress-nginx, cert-manager
                                  #   ml-gpu        — GPU Operator, Argo Workflows, Kubeflow Training Operator
                                  #   edge          — MetalLB, Longhorn
                                  #   multi-tenant  — ArgoCD, cert-manager, ingress-nginx, Capsule

monitoring: prometheus            # Options: prometheus | prometheus-loki | none
                                  #   prometheus       — kube-prometheus-stack (Prometheus + Grafana + Alertmanager)
                                  #   prometheus-loki  — above + Loki (log aggregation) + Promtail
                                  #   none             — skip monitoring entirely

# ── Node lists ────────────────────────────────────────────────────────────────

masters:                          # Control plane nodes. 1 = no HA. 3+ = HA mode.
  - name: master-1                # Hostname label (used in output and logs)
    ip: 192.168.1.10              # IP that the MCP server can SSH to
    user: ubuntu                  # SSH username
    ssh_key: ~/.ssh/id_rsa        # Path to private key on the MCP server machine
    os_family: auto               # Optional. auto | debian | rhel | suse
                                  # auto = SSH in and detect from /etc/os-release

workers:
  - name: worker-1
    ip: 192.168.1.20
    user: ubuntu
    ssh_key: ~/.ssh/id_rsa
    # os_family omitted — auto-detected

# ── Optional: proxy ──────────────────────────────────────────────────────────
# Remove this entire block if your servers have direct internet access.
# If present, applies to: apt/dnf/zypper, containerd (systemd drop-in),
# curl, helm repo add, helm upgrade, kubectl apply -f <url>.

proxy:
  http_proxy:  "http://proxy.corp.local:3128"
  https_proxy: "http://proxy.corp.local:3128"
  no_proxy:    "localhost,127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.svc,.cluster.local,.corp.local"

# ── Optional: node_config ─────────────────────────────────────────────────────
# Controls what prepare_nodes does to every node beyond installing kubeadm.
# All fields have defaults — omit to use defaults.

node_config:
  sysctl_preset: k8s-minimal      # k8s-minimal (3 params) | k8s-production (13 params) | k8s-highperf (21 params) | custom
  sysctl_custom: {}               # Extra sysctl params merged on top of the preset.
                                  # Example: {vm.max_map_count: "262144"}  (needed for Elasticsearch)

  kernel_modules: required        # Which kernel modules to load beyond overlay+br_netfilter:
                                  #   required    — only overlay + br_netfilter (always safe)
                                  #   ipvs        — adds ip_vs, ip_vs_rr, ip_vs_wrr, ip_vs_sh, nf_conntrack
                                  #   ipvs_legacy — same but nf_conntrack_ipv4 (older kernels)
                                  #   ebpf_extra  — adds nf_conntrack (used by Cilium eBPF mode)
                                  #   none        — only the two required modules
  extra_modules: []               # Any additional module names to load.

  iptables_mode: auto             # auto | legacy | nftables
                                  #   auto    — let the OS decide (correct for most cases)
                                  #   legacy  — force iptables-legacy (for older CNIs or kernels < 4.18)
                                  #   nftables— install and enable nftables

  selinux: permissive             # RHEL/CentOS family only. Ignored on Debian/SUSE.
                                  #   permissive — setenforce 0 + SELINUX=permissive in /etc/selinux/config
                                  #   enforcing  — leave as-is. Ensure your CNI supports SELinux contexts.
                                  #   disabled   — SELINUX=disabled (takes effect after reboot)

  swap: disable                   # disable | keep | warn
                                  #   disable — swapoff -a and comment out /etc/fstab (permanent)
                                  #   warn    — swapoff at runtime only (comes back after reboot)
                                  #   keep    — do nothing (add --fail-swap-on=false to kubelet yourself)

  hugepages: false                # false — disable transparent hugepages (recommended)
                                  # true  — leave THP enabled (some ML workloads prefer it)

  ulimits: true                   # true  — write /etc/security/limits.d/99-k8s.conf
                                  #         (nofile 1048576, nproc 65536)
                                  #         Prevents "too many open files" at high pod density
                                  # false — skip

# ── Optional: CNI options ──────────────────────────────────────────────────────
# Override any Helm values for your chosen CNI.
cni_options:
  routingMode: native             # Example: switch Cilium from VXLAN to native routing
  bgpControlPlane.enabled: "true"

# ── Optional: extra Helm packages ─────────────────────────────────────────────
extra_helm_packages:
  - repo:    longhorn
    url:     https://charts.longhorn.io
    chart:   longhorn/longhorn
    release: longhorn
    ns:      longhorn-system

# ── Optional: cloud provider and costing ──────────────────────────────────────
cloud_provider: onprem            # aws | gcp | azure | onprem | openstack
                                  # Used by cost_report to determine how to calculate costs.

costing:
  rates:
    cpu_core_hourly_usd:    0.015  # Cost per vCPU per hour (on-prem estimate)
    ram_gb_hourly_usd:      0.005  # Cost per GiB RAM per hour
    storage_gb_monthly_usd: 0.10   # Cost per GiB persistent storage per month
    power_kwh_usd:          0.12   # Electricity cost per kWh (for power estimate)
    currency: USD                  # Currency label in reports

# ── Global dry-run mode (optional) ───────────────────────────────────────────
# Set to true to run every tool in preview mode — no changes to any server.
# Equivalent to passing dry_run: true to every individual tool call.
# Useful for reviewing a full plan before committing to execute it.
# global_dry_run: false

# ── Session notes ─────────────────────────────────────────────────────────────
# Session state is saved automatically to ~/.k8s-mcp/state.json on the machine
# running the MCP server after every successful tool call. You can close the
# terminal and resume the session later — plan_cluster does not need to be re-run.
# Use save_cluster / switch_cluster to manage multiple named cluster sessions.
# Every tool call is logged to ~/.k8s-mcp/audit.log with secrets masked.
```

---

## 9. All 41 tools — complete reference

### How tools are organised

The 41 tools fall into seven groups:

```
Group A — Cluster lifecycle (8 tools)
  preflight_check → plan_cluster → prepare_nodes → bootstrap_cluster →
  install_cni → install_stack → cluster_status → destroy_cluster

Group B — Applications and services (5 tools)
  install_monitoring, install_jenkins, install_cert_manager,
  install_security_tools, install_applications

Group C — Security hardening (6 tools)
  configure_rbac, configure_pod_security, configure_etcd_encryption,
  configure_audit_logging, security_audit, audit_cluster

Group D — Day-2 operations (9 tools)
  scale_cluster, upgrade_cluster, backup_etcd, restore_etcd, rotate_certs,
  renew_service_cert, helm_manage, cluster_snapshot, migrate_workload

Group E — Observability and access (5 tools)
  cluster_status, node_diagnostics, stream_logs, manage_kubeconfig,
  provision_namespace

Group F — Reporting and storage (4 tools)
  generate_cluster_report, cost_report, provision_storage, audit_cluster

Group G — Session, multi-cluster, validation, and audit (7 tools)
  validate_config, save_cluster, switch_cluster, list_clusters,
  delete_cluster, show_audit_log, and the audit trail system itself
```

Every tool that touches the network supports `dry_run: true` — which prints the exact commands that would run without executing them. Setting `global_dry_run: true` in the cluster config applies dry-run mode to every tool in the session automatically.

---

### Group A — Cluster lifecycle

#### `plan_cluster`

**What it does:** Validates your cluster config YAML and returns a complete execution plan. Stores the config in the MCP server's session memory so all subsequent tools can use it without you repeating settings. Does not touch any servers.

**Required parameter:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `config` | string | The full cluster_config.yaml contents (paste as a block) |

**What plan_cluster checks:**
- All required fields are present (`cluster_name`, `k8s_version`, `cni`, `pod_cidr`, `service_cidr`, `profile`, `masters`, `workers`)
- `cni` is one of: `cilium`, `calico`, `flannel`, `weave`
- `profile` is one of: `production`, `development`, `ml-gpu`, `edge`, `multi-tenant`
- `monitoring` is one of: `prometheus`, `prometheus-loki`, `none`
- `node_config` values are within supported options
- `proxy` block has at least one of `http_proxy` or `https_proxy` if present

**What the output shows:**
- Summary of all settings
- The node_config that will be applied (with defaults shown for any field you omitted)
- The five phases that follow
- A list of Helm packages that will be installed for your profile
- A note about proxy status (configured vs direct internet)
- Suggestions for additional config options you might want to add

**Example conversation:**
```
You: Plan this cluster: [paste your config YAML]
Claude: [calls plan_cluster, shows the plan, offers numbered next-step choices]
```

---

#### `prepare_nodes`

**What it does:** SSHes into every master and worker node simultaneously (using a thread pool — all nodes run in parallel, not one at a time). On each node it:

1. Detects the OS from `/etc/os-release` (unless `os_family` is set explicitly in config)
2. Runs the prep script tailored for that OS family
3. Reports the detected OS and result per node

**The prep script does, in order:**
1. Export proxy env vars if configured
2. Write the package manager proxy config file (`/etc/apt/apt.conf.d/95proxies` or `/etc/dnf/dnf.conf`)
3. Handle swap (disable permanently, disable at runtime, or leave)
4. Handle SELinux (RHEL only)
5. Load kernel modules (`overlay`, `br_netfilter`, plus any from `kernel_modules` setting)
6. Write `/etc/sysctl.d/k8s.conf` with sysctl parameters from your chosen preset
7. Set iptables mode if configured
8. Set system ulimits if enabled
9. Configure transparent hugepages
10. Install containerd
11. Write containerd proxy drop-in (systemd unit override — daemons do not inherit shell env vars)
12. Restart and enable containerd
13. Add the Kubernetes apt/yum/zypper repository
14. Install `kubelet`, `kubeadm`, `kubectl` at the specified version
15. Pin (hold) the package versions to prevent accidental upgrades
16. Enable the kubelet service

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dry_run` | boolean | false | Show the generated script for a Debian node without running it |

**Why prepare_nodes runs in parallel:** With 10 nodes, serial execution would take 10× longer. The thread pool runs all nodes simultaneously. The only ordering constraint is that `prepare_nodes` must complete on all nodes before `bootstrap_cluster` starts.

---

#### `bootstrap_cluster`

**What it does:** Turns prepared nodes into an actual Kubernetes cluster.

**Process:**
1. Runs `kubeadm init` on the first master with your `pod_cidr`, `service_cidr`, and `k8s_version`
2. Saves the kubeconfig to the MCP server's session state
3. If you have 2+ masters (HA mode): extracts the certificate key and runs `kubeadm join --control-plane --certificate-key <key>` on each additional master (sequentially — each needs the previous one stable)
4. Runs `kubeadm join` on all workers (in parallel)

**What `kubeadm init` actually sets up:**
- The Kubernetes API server (the brain of the cluster)
- etcd (the database that stores all cluster state)
- The scheduler (decides which node runs each pod)
- The controller manager (keeps the desired state in sync with reality)
- Generates all TLS certificates for secure communication

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dry_run` | boolean | false | Show the kubeadm init command without running it |

**After bootstrap_cluster:** Nodes will show `NotReady` in `kubectl get nodes`. This is expected — they need a CNI plugin before pod networking works.

---

#### `install_cni`

**What it does:** Installs the CNI (Container Network Interface) plugin you chose in your config. After this, nodes flip to `Ready` and pods can communicate.

**CNI options:**

| CNI | Install method | Default config applied |
|-----|---------------|----------------------|
| `cilium` | Helm `cilium/cilium` v1.15.6 | `kubeProxyReplacement=true`, `ipam.mode=kubernetes`, `hubble.relay.enabled=true`, `hubble.ui.enabled=true` |
| `calico` | Helm `projectcalico/tigera-operator` v3.28.0 | Tigera operator default values |
| `flannel` | `kubectl apply -f` from GitHub release | VXLAN overlay mode |
| `weave` | `kubectl apply -f` from GitHub release | Mesh overlay mode |

Override any CNI Helm value by adding `cni_options` to your config:
```yaml
cni_options:
  kubeProxyReplacement: "strict"   # Stricter Cilium mode
  hubble.metrics.enabled: "drop,port,flow"
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dry_run` | boolean | false | Show the Helm command without running it |

---

#### `install_stack`

**What it does:** Installs the Helm package set for your profile.

**Packages installed per profile:**

| Profile | Packages |
|---------|---------|
| `production` | ArgoCD (GitOps), cert-manager (TLS), ingress-nginx (HTTP routing), MetalLB (LoadBalancer IPs), Velero (backups) |
| `development` | ArgoCD, ingress-nginx, cert-manager, Kubernetes Dashboard |
| `ml-gpu` | NVIDIA GPU Operator, Argo Workflows, Kubeflow Training Operator |
| `edge` | MetalLB, Longhorn (distributed storage) |
| `multi-tenant` | ArgoCD, cert-manager, ingress-nginx, Capsule (namespace isolation per tenant) |

**Extra packages:** Add to `extra_helm_packages` in config — any Helm chart can be added this way.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `packages` | array | all profile packages | Optional: install only a named subset |
| `dry_run` | boolean | false | Show all Helm commands without running them |

---

#### `cluster_status`

**What it does:** Runs five read-only health checks against the cluster and returns the results:

1. `kubectl get nodes -o wide` — node Ready/NotReady status, versions, IPs
2. `kubectl get pods -n kube-system -o wide` — control plane component health
3. Pods not in Running or Succeeded state across all namespaces
4. Persistent volumes and their claim status
5. LoadBalancer-type services and their external IPs

**No parameters.** Safe to run at any time.

---

#### `destroy_cluster`

**What it does:** Runs `kubeadm reset -f` on every node simultaneously, then clears iptables rules and deletes Kubernetes data directories. This is irreversible.

**What gets deleted:**
- `/etc/kubernetes/` — all kubeadm config and certs
- `/var/lib/etcd/` — all cluster state data
- `/var/lib/kubelet/` — kubelet data
- `/etc/cni/net.d/` — CNI config
- All iptables rules (nat, mangle, filter tables)

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `confirm` | string | yes | Must be exactly `DESTROY` — anything else is rejected |

---

### Group B — Applications and services

#### `install_monitoring`

**What it does:** Installs a monitoring stack via Helm.

**Options:**

| Type | What installs | Port-forward to access |
|------|--------------|----------------------|
| `prometheus` | kube-prometheus-stack: Prometheus, Grafana, Alertmanager | `kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80` |
| `prometheus-loki` | Everything above + Loki (log storage) + Promtail (log collector running on every node) | Same — Grafana has a Loki data source added automatically |
| `none` | Nothing | — |

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `monitoring_type` | string | yes | — | `prometheus`, `prometheus-loki`, or `none` |
| `grafana_password` | string | no | `admin-changeme` | Grafana admin password — **change this before production use** |
| `dry_run` | boolean | no | false | Show Helm commands without running |

---

#### `install_jenkins`

**What it does:** Installs Jenkins via the official Helm chart, configured for in-cluster use only.

**What gets configured:**
- Service type: `ClusterIP` (no external exposure — access via port-forward)
- Persistent volume: 10Gi for `JENKINS_HOME` (retains jobs, config, and credentials across restarts)
- RBAC: ServiceAccount with permissions to list pods/secrets in its namespace
- Kubernetes plugin: pre-installed so Jenkins can spawn build agent pods in this same cluster — no separate credentials needed for that

**Access:**
```bash
kubectl port-forward -n jenkins svc/jenkins 8080:8080
# Then open: http://localhost:8080
# Login: admin / <password you set>
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `admin_password` | string | `admin-changeme` | Jenkins admin password — change before production use |
| `storage_size` | string | `10Gi` | Size of the PVC for JENKINS_HOME |
| `storage_class` | string | cluster default | StorageClass for the PVC |
| `dry_run` | boolean | false | Show Helm command without running |

---

#### `install_cert_manager`

**What it does:** Installs cert-manager (the Kubernetes certificate lifecycle controller) and creates a `ClusterIssuer` — the resource that tells cert-manager how to issue certificates.

**Issuer types:**

| Type | When to use | What it does |
|------|-------------|--------------|
| `self-signed` | On-prem, no public DNS | Creates a self-signed cluster CA; issues certs from that CA. No internet required. |
| `acme-letsencrypt` | Public DNS, port 80/443 reachable | Uses Let's Encrypt's free ACME service. Requires an email address. |
| `acme-zerossl` | Public DNS, port 80/443 reachable | ZeroSSL's ACME service — alternative to Let's Encrypt |
| `internal-ca` | Enterprise with existing PKI | Uses your own CA cert+key to sign. Provide them base64-encoded. |

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `issuer_type` | string | no | `self-signed` | `self-signed`, `acme-letsencrypt`, `acme-zerossl`, `internal-ca` |
| `email` | string | if ACME | — | Your email for ACME account registration |
| `ca_cert` | string | if `internal-ca` | — | Base64-encoded CA certificate |
| `ca_key` | string | if `internal-ca` | — | Base64-encoded CA private key |
| `dry_run` | boolean | no | false | Show Helm command and issuer manifest |

---

#### `install_security_tools`

**What it does:** Installs any combination of four in-cluster security tools. Claude will ask you which ones you want if you don't specify.

**Available tools:**

| Tool | What it does | Why you'd use it |
|------|-------------|-----------------|
| `falco` | Watches Linux syscalls in real time and alerts on anomalous behaviour (e.g. a container reading /etc/passwd) | Runtime threat detection — catches attacks that slip past image scanning |
| `gatekeeper` | OPA (Open Policy Agent) Gatekeeper — validates all resource creation requests against your policies before they land | Policy enforcement — e.g. "all containers must have resource limits" |
| `trivy-operator` | Scans every container image running in the cluster for known CVEs; stores results as Kubernetes CRDs you can query | Vulnerability management without a separate pipeline |
| `kyverno` | Policy-as-code engine like Gatekeeper but with simpler YAML-based policy syntax | Easier to get started with than OPA |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tools` | array | yes | One or more of: `falco`, `gatekeeper`, `trivy-operator`, `kyverno` |
| `dry_run` | boolean | no | Show Helm commands without running |

---

#### `install_applications`

**What it does:** Installs additional DevOps applications into the cluster. Generates and stores credentials for each application, which are then included in the cluster report.

**Available applications:**

| Application | What it does | Access |
|-------------|-------------|--------|
| `sonarqube` | Code quality analysis and SAST (static application security testing). Scans source code for bugs, security issues, and code smells. | Port-forward to 9000 |
| `harbor` | Private container image registry with built-in Trivy vulnerability scanning, image replication, and access control. | Port-forward to 8080 |
| `vault` | HashiCorp Vault for secrets management. Generates unseal keys and root token on install. Configures the Kubernetes auth method automatically so pods can authenticate to Vault using their ServiceAccount tokens. | Port-forward to 8200 |
| `keycloak` | SSO / OIDC identity provider. Creates a realm and admin account. Wires kube-apiserver to trust this Keycloak instance for OIDC authentication. | Port-forward to 8080 |

**Vault initialisation note:** When Vault is installed, it is initialised and the unseal keys + root token are captured into session state. They are included in the cluster report. **These are shown only once — save the report.**

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `apps` | array | yes | One or more of: `sonarqube`, `harbor`, `vault`, `keycloak` |
| `storage_class` | string | no | StorageClass for persistent volumes. Uses cluster default if omitted. |
| `dry_run` | boolean | no | Show Helm commands without running |

---

### Group C — Security hardening

#### `configure_rbac`

**What it does:** Applies cluster-level RBAC hardening in three steps:

1. **Patches all default ServiceAccounts** across every namespace to set `automountServiceAccountToken: false`. This prevents every pod from silently having an API token unless you explicitly opt in — a common attack vector.
2. **Removes the anonymous cluster-admin binding** if it exists (it should not, but this is a safety net).
3. **Writes an audit policy file** to `/etc/kubernetes/audit-policy.yaml`.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `audit_level` | string | `metadata` | `none`, `metadata`, `request`, `requestresponse` (see configure_audit_logging) |
| `restrict_default_sa` | boolean | true | Patch all default ServiceAccounts with `automountServiceAccountToken: false` |
| `dry_run` | boolean | false | Show what would change without applying |

---

#### `configure_pod_security`

**What it does:** Configures two layered defences that restrict what pods can do inside the cluster.

**Pod Security Admission (PSA):**
PSA is a built-in Kubernetes admission controller (available since K8s 1.23, stable since 1.25) that enforces security standards at the namespace level. It replaces the deprecated PodSecurityPolicy.

| Mode | What it enforces |
|------|----------------|
| `privileged` | No restrictions (default — avoid in production) |
| `baseline` | Blocks the most dangerous settings: hostPID, hostIPC, privileged containers, hostPath mounts to sensitive paths |
| `restricted` | Everything in baseline plus: no root user, read-only root filesystem required, seccomp profile required, no capability escalation |

**Default-deny NetworkPolicy:**
When `default_deny_network: true`, a NetworkPolicy is applied to every non-system namespace that blocks all ingress and egress by default. Applications then explicitly open only the ports they need.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mode` | string | `baseline` | PSA mode: `privileged`, `baseline`, `restricted` |
| `default_deny_network` | boolean | true | Apply default-deny NetworkPolicy to all non-system namespaces |
| `dry_run` | boolean | false | Show manifests without applying |

---

#### `configure_etcd_encryption`

**What it does:** Configures Kubernetes Secrets to be encrypted at rest inside etcd.

By default, Kubernetes Secrets are stored in etcd as base64-encoded text — not encrypted. Anyone with access to the etcd data directory can read all your secrets. Encryption at rest protects against:
- Direct etcd disk access (physical server access, snapshot theft)
- etcd backup files being read by unauthorised parties

**How it works:**
1. Generates a random 32-byte key
2. Writes an `EncryptionConfiguration` file to `/etc/kubernetes/encryption/config.yaml`
3. Adds the `--encryption-provider-config` flag to the kube-apiserver manifest
4. Re-writes all existing Secrets through the API to encrypt them with the new key

**Algorithms:**

| Algorithm | What it is | When to use |
|-----------|-----------|-------------|
| `aes-cbc` | AES-256 in CBC mode | Widest compatibility (K8s 1.13+) |
| `aes-gcm` | AES-256 in GCM mode | Faster, authenticated encryption — K8s 1.25+ |

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `algorithm` | string | `aes-cbc` | `aes-cbc` or `aes-gcm` |
| `dry_run` | boolean | false | Show the EncryptionConfiguration without applying |

**Important:** Back up etcd before running this. The encryption key is printed once in the tool output and saved in the cluster report. If the key is lost, Secrets cannot be decrypted.

---

#### `configure_audit_logging`

**What it does:** Configures the Kubernetes API server to write an audit log — a record of every request made to the cluster.

**Audit levels:**

| Level | What is logged | Use when |
|-------|---------------|---------|
| `none` | Nothing | Testing only |
| `metadata` | Who made a request, what they accessed, and when — no request/response bodies | Good balance for production |
| `request` | Everything in metadata plus the request body | When you need to see what was submitted |
| `requestresponse` | Everything plus the response body | Maximum detail — high volume, use only for specific resources |

The tool writes a policy file that applies different levels to different resource types:
- Secrets get `metadata` level at minimum (you want to know who reads secrets)
- RBAC resources get logged
- Health check endpoints are excluded (too noisy)

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `level` | string | `metadata` | `none`, `metadata`, `request`, `requestresponse` |
| `log_path` | string | `/var/log/kubernetes/audit.log` | Where to write audit logs on the master |
| `max_age` | integer | 30 | Days to retain log files before rotation |
| `dry_run` | boolean | false | Show the audit policy file without applying |

---

#### `security_audit`

**What it does:** Runs a multi-standard compliance audit against the live cluster. Claude will ask you which standards to run if not specified.

**Standards and checks:**

| Standard | Controls checked |
|----------|-----------------|
| **CIS Kubernetes Benchmark** (9 checks) | API server pod spec permissions, anonymous-auth disabled, insecure port disabled, admission controllers configured, etcd peer certs, kubelet anonymous auth, no wildcard RBAC verbs, no privileged containers, namespaces have NetworkPolicies |
| **NSA/CISA Kubernetes Hardening Guide** (5 checks) | Non-root containers, immutable root filesystems, privilege escalation disabled, resource limits on all containers, no sensitive hostPath mounts |
| **PCI-DSS** (4 checks) | Default SA token automount disabled, no cluster-admin bindings to users, unique ServiceAccount per workload, audit logging enabled |
| **SOC2 / ISO27001** (5 checks) | Secrets not in env vars, no `latest` image tags, Trivy Operator installed, RBAC enabled, etcd encryption configured |

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `standards` | array | `["all"]` | One or more of: `cis`, `nsa-cisa`, `pci-dss`, `soc2-iso27001`, `all` |
| `output_report` | boolean | true | Include audit results in the cluster report |

---

#### `audit_cluster`

**What it does:** An older operational audit tool (predates `security_audit`). Checks for: privileged pods, root-user containers, pods missing resource limits, NodePort services, non-system ClusterRoleBindings, unbound PVCs, and certificate expiry. Run `security_audit` for full compliance checking; use `audit_cluster` for a quick operational health sweep.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `checks` | array | `["all"]` | One or more of: `security`, `rbac`, `resources`, `networking`, `storage`, `certificates`, `all` |

---

### Group D — Day-2 operations

#### `scale_cluster`

**What it does:** Adds new nodes to a live cluster, or drains and removes existing ones — without taking the cluster down.

**Adding nodes (action: add):**
1. Detects the OS on each new node (same detection as `prepare_nodes`)
2. Runs the full prep script on each new node (in parallel)
3. Generates a fresh `kubeadm join` token (tokens expire, so a new one is always created)
4. If role is `master`: uses the certificate key to join as a control-plane node
5. If role is `worker`: runs `kubeadm join` to join as a worker

**Draining nodes (action: drain):**
Runs `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --force`. This evicts all pods from the node (rescheduling them elsewhere) and marks it unschedulable.

**Removing nodes (action: remove):**
Drain first, then `kubectl delete node <name>`. The node is removed from the cluster but the VM still exists.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `action` | string | yes | — | `add`, `drain`, or `remove` |
| `role` | string | no | `worker` | For add: `worker` or `master` |
| `nodes` | array | yes | — | For add: `[{name, ip, user, ssh_key, os_family?}]`. For drain/remove: list of node name strings |
| `dry_run` | boolean | no | false | Show what would happen |

---

#### `upgrade_cluster`

**What it does:** Performs a rolling Kubernetes version upgrade with no application downtime.

**Process:**
1. Upgrades the first master: unpin kubeadm, install new version, run `kubeadm upgrade apply v<version>`, upgrade kubelet and kubectl, restart kubelet
2. Upgrades additional masters (if HA): same steps, one at a time sequentially
3. Upgrades workers in batches (default: 3 at a time): drain the batch → upgrade in parallel → uncordon

The batch approach means applications always have running pods somewhere in the cluster during the upgrade.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `target_version` | string | yes | — | Target K8s version e.g. `1.31` |
| `worker_batch_size` | integer | no | 3 | Workers upgraded simultaneously per batch |
| `dry_run` | boolean | no | false | Show the plan without running |

---

#### `backup_etcd`

**What it does:** Creates a timestamped etcd snapshot on the first master node using `etcdctl snapshot save`.

The snapshot filename format: `snapshot-YYYYMMDD-HHMMSS.db`

The snapshot uses the cluster's own PKI certificates for authentication to etcd:
- CA: `/etc/kubernetes/pki/etcd/ca.crt`
- Client cert: `/etc/kubernetes/pki/etcd/server.crt`
- Client key: `/etc/kubernetes/pki/etcd/server.key`

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `backup_path` | string | `/opt/etcd-backups/snapshot.db` | Base path; timestamp is inserted before `.db` |

**Schedule this regularly.** Run it before every significant change: upgrades, etcd encryption configuration, large deployments. There is no automatic scheduling built into this tool — add it to a CronJob or call it manually.

---

#### `restore_etcd`

**What it does:** Restores etcd from a snapshot file. Temporarily stops the control plane.

**Process:**
1. Moves `/etc/kubernetes/manifests` to `.bak` — this stops the control plane static pods
2. Waits 5 seconds for pods to terminate
3. Runs `etcdctl snapshot restore` to the new data directory
4. Swaps the old and new data directories
5. Moves manifests back — control plane restarts
6. Verifies nodes are visible

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `snapshot_path` | string | yes | Full path to the `.db` snapshot file on the master |
| `confirm` | string | yes | Must be exactly `RESTORE` |

**HA cluster warning:** On a multi-master cluster, restoring etcd on only one master desynchronises the etcd cluster. Stop etcd on all masters before restoring, restore on one, then let the others rejoin and resync. This tool handles the single-master case automatically and prints a warning for HA clusters.

---

#### `rotate_certs`

**What it does:** Renews all kubeadm-managed TLS certificates on every master node, in parallel.

Certificates renewed: `apiserver`, `apiserver-etcd-client`, `apiserver-kubelet-client`, `front-proxy-client`, `etcd/healthcheck-client`, `etcd/peer`, `etcd/server`.

After renewing, kubelet is restarted and the kubeconfig is updated.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `check_only` | boolean | false | Show expiry dates without renewing |

**Zero downtime:** Certificate rotation is done on each master while the others continue serving traffic. There is a brief restart of kubelet per master. No application pods are evicted.

---

#### `renew_service_cert`

**What it does:** Triggers immediate renewal of a cert-manager-managed certificate for a specific service — without any pod restarts.

cert-manager rotates the certificate secret transparently: the new cert is written to the Secret, and any pods that mount that Secret via a volume will see the update within a few seconds (kubelet hot-reloads mounted secrets automatically).

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `certificate_name` | string | yes | — | Name of the cert-manager `Certificate` resource (`kubectl get certificates -A`) |
| `namespace` | string | no | `default` | Namespace where the Certificate lives |
| `force` | boolean | no | false | Delete and recreate the underlying Secret (forces full re-issuance, not just renewal trigger) |

---

#### `helm_manage`

**What it does:** A Swiss-army-knife for managing Helm releases on the cluster.

**Actions:**

| Action | What it does |
|--------|-------------|
| `list` | Show all Helm releases (version, status, chart, namespace) |
| `status` | Detailed status of a specific release |
| `history` | Revision history of a release |
| `upgrade` | Upgrade to a new chart version or change values |
| `rollback` | Roll back to a specific revision number |
| `uninstall` | Remove a release and its resources |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | One of the actions above |
| `release` | string | for most actions | Release name |
| `namespace` | string | no | Namespace of the release. Omit for all-namespace listing |
| `chart` | string | for upgrade | Chart reference e.g. `argo/argo-cd` |
| `version` | string | no | Chart version for upgrade |
| `revision` | integer | for rollback | Revision number to roll back to |
| `dry_run` | boolean | no | Show what would change |

---

#### `cluster_snapshot`

**What it does:** Dumps every non-secret Kubernetes resource to YAML files on the master node, organised by namespace. Useful for GitOps — commit the snapshot to version control to track what is deployed.

Resources exported: `all`, `configmap`, `ingress`, `networkpolicy`, `pvc`, `serviceaccount`, `rolebinding`, `role`, and optionally `secret`.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `output_dir` | string | `/opt/cluster-snapshot` | Base directory on master. A timestamped subdirectory is created. |
| `namespaces` | array | all namespaces | Specific namespaces to export |
| `exclude_secrets` | boolean | true | Whether to exclude Secret resources |

---

#### `migrate_workload`

**What it does:** Converts an existing application definition (docker-compose.yml or systemd unit file) into Kubernetes manifests.

**For docker-compose.yml:** Each service becomes a Deployment + Service. The tool extracts:
- Container image
- Port mappings → containerPort + Service port
- Environment variables → env vars in the container spec
- Volume mounts → a hint comment with a PVC template

**Generated manifest includes:**
- Resource requests and limits (CPU: 100m/500m, Memory: 128Mi/512Mi — edit as needed)
- Liveness and readiness probes using TCP socket check on the first port
- `imagePullPolicy: IfNotPresent`

**Optional additions:**

| Option | What is added |
|--------|--------------|
| `add_hpa: true` | HorizontalPodAutoscaler scaling from `replicas` to `5×replicas` at 70% CPU |
| `add_pdb: true` | PodDisruptionBudget with `minAvailable: 1` |

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source_type` | string | yes | — | `docker-compose` or `systemd` |
| `source` | string | yes | — | The full file contents to convert |
| `namespace` | string | no | `default` | Target K8s namespace |
| `replicas` | integer | no | 1 | Initial replica count |
| `add_hpa` | boolean | no | false | Generate HPA |
| `add_pdb` | boolean | no | false | Generate PDB |

---

### Group E — Observability and access

#### `node_diagnostics`

**What it does:** SSHes into nodes in parallel and collects deep diagnostic information including:
- Hostname and OS details from `/etc/os-release`
- Kernel version
- Disk usage per mount point
- Memory (total / used / free / swap)
- CPU count and load average
- kubelet service status
- Last 20 kubelet journal log entries
- containerd service status
- OOM (Out of Memory) events from kernel ring buffer (`dmesg`)
- Network interfaces with IP addresses
- Socket statistics summary

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `node_name` | string | all nodes | Run diagnostics only on this node |

---

#### `stream_logs`

**What it does:** Fetches logs from running pods. Equivalent to `kubectl logs` with a few convenient options.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `namespace` | string | `default` | Namespace to fetch logs from |
| `pod` | string | — | Specific pod name |
| `selector` | string | — | Label selector e.g. `app=nginx` (used when pod not specified) |
| `container` | string | — | Container name in multi-container pods |
| `tail_lines` | integer | 50 | Number of recent lines to return |
| `previous` | boolean | false | Fetch logs from the previous (crashed) container instance |

**Use `previous: true` after a crash** to see what the container printed before it exited.

---

#### `manage_kubeconfig`

**What it does:** Creates a scoped kubeconfig file for a person or CI system that should have limited access to the cluster.

**Process:**
1. Creates a ServiceAccount with the given username in the target namespace
2. Creates a RoleBinding binding the chosen ClusterRole to that ServiceAccount
3. Generates a 1-year bearer token using `kubectl create token`
4. Assembles a valid kubeconfig and saves it locally

**Roles available:**

| Role | Can do |
|------|--------|
| `view` | Read all resources in the namespace |
| `edit` | Read + create + update + delete most resources (not RBAC) |
| `admin` | Full control of the namespace including RBAC |

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `username` | string | yes | — | ServiceAccount name and kubeconfig user name |
| `namespace` | string | yes | — | Namespace to scope the access to |
| `role` | string | no | `view` | `view`, `edit`, or `admin` |
| `output_path` | string | no | `./kubeconfig-user.yaml` | Where to write the kubeconfig locally |

---

#### `provision_namespace`

**What it does:** Creates a namespace with three linked resources in one operation:

1. **Namespace** — with a `team:` label
2. **ResourceQuota** — total CPU and memory limits for everything in the namespace
3. **LimitRange** — default resource requests and limits applied to containers that don't specify their own
4. **RoleBinding** — binds the `admin` ClusterRole to a group named after the team

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | yes | — | Namespace name |
| `team` | string | yes | — | Team name — becomes the RBAC group name |
| `cpu_limit` | string | no | `8` | Total CPU cores the namespace can use |
| `mem_limit` | string | no | `16Gi` | Total memory the namespace can use |
| `cpu_req` | string | no | `4` | Total CPU requests (reserved) |
| `mem_req` | string | no | `8Gi` | Total memory requests |

---

### Group F — Reporting and storage

#### `generate_cluster_report`

**What it does:** Collects all information about the cluster and writes two files to the master node:

- `cluster-report.md` — human-readable Markdown, suitable for sharing with a team
- `cluster-report.yaml` — machine-readable YAML, suitable for feeding into automation

**Contents of the report:**

| Section | What is included |
|---------|-----------------|
| Cluster overview | Name, version, CNI, profile, pod/service CIDRs, HA status, proxy |
| Node configuration | Every node_config setting that was applied |
| Nodes | `kubectl get nodes -o wide` output |
| Namespaces | All namespaces |
| Network | CIDRs, NetworkPolicies |
| Services | All services across all namespaces |
| Persistent volumes | All PVs and their status |
| Certificate expiry | kubeadm cert expiry dates, cert-manager Certificate statuses |
| ServiceAccounts | All SAs across all namespaces |
| **Credentials** | Jenkins, Grafana, SonarQube, Harbor, Vault (unseal keys + root token), Keycloak admin |
| Security tools | Which tools are installed |
| Compliance audit | Last audit results (pass/fail count per standard) |
| etcd encryption | Algorithm configured |
| cert-manager | Issuer type |
| Cost estimate | Monthly estimate if cost_report was run |
| Next actions | Checklist of recommended follow-up steps |

**Files are written with `chmod 600`** — readable only by the file owner. Treat these files as sensitive.

**To retrieve from the master:**
```bash
scp user@master-ip:/opt/cluster-report/*/cluster-report.md ./
scp user@master-ip:/opt/cluster-report/*/cluster-report.yaml ./
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `output_dir` | string | `/opt/cluster-report` | Base directory; timestamped subdirectory is created inside |
| `include_secrets` | boolean | true | Include credential values. Set `false` for reports you will share with others. |

---

#### `cost_report`

**What it does:** Reads actual resource requests from the cluster (not allocatable capacity — what is actually requested) and calculates a cost estimate.

**How costs are calculated:**

For on-prem and OpenStack:
```
cost_per_month = 
  (total_cpu_cores × cpu_core_hourly_usd × 730)
  + (total_ram_gib × ram_gb_hourly_usd × 730)
  + (total_pvc_gib × storage_gb_monthly_usd)
```

730 = average hours per month (365 days × 24 hours ÷ 12).

For AWS, GCP, Azure: the tool notes what cloud CLI commands would be needed and provides the consumption-based estimate above while real billing API integration is pending.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `cloud_provider` | string | from config | `aws`, `gcp`, `azure`, `onprem`, `openstack` |
| `aws_profile` | string | — | AWS CLI profile for Cost Explorer API |
| `gcp_project` | string | — | GCP project ID |
| `azure_sub` | string | — | Azure subscription ID |
| `breakdown` | string | `all` | `namespace`, `node`, `component`, or `all` |

**Customise the per-unit rates** in your cluster config:
```yaml
costing:
  rates:
    cpu_core_hourly_usd: 0.020   # adjust to your hardware costs
    ram_gb_hourly_usd:   0.006
    storage_gb_monthly_usd: 0.08
    currency: EUR
```

---

#### `provision_storage`

**What it does:** Installs a StorageClass so that PersistentVolumeClaims in the cluster can be automatically fulfilled.

**StorageClass options:**

| Type | Install method | What it provides | When to use |
|------|---------------|-----------------|-------------|
| `longhorn` | Helm | Distributed block storage replicated across nodes | On-prem production — survives node failure |
| `nfs` | Helm | Shared NFS-backed persistent volumes | When you have an existing NFS server |
| `local-path` | kubectl apply | Node-local directories — not replicated | Dev/test only; data is lost if the node fails |
| `rook-ceph` | Helm | Full Ceph distributed storage cluster | Large-scale production; requires 3+ nodes with raw block devices |

Setting `set_default: true` (the default) patches the StorageClass with the annotation that makes it the default — any PVC that doesn't specify a StorageClass will use this one.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `type` | string | yes | — | `longhorn`, `nfs`, `local-path`, `rook-ceph` |
| `set_default` | boolean | no | true | Make this the cluster default StorageClass |
| `nfs_server` | string | if nfs | — | IP address of your NFS server |
| `nfs_path` | string | if nfs | — | NFS export path e.g. `/srv/nfs/k8s` |
| `dry_run` | boolean | no | false | Show Helm command without running |

---

### Group G — Session, multi-cluster, validation, and audit

This group manages how the MCP server stores state, handles multiple clusters, validates configs offline, and keeps a compliance audit trail of every action taken.

#### How session state works

Every time a tool call succeeds, the MCP server automatically writes the current session state to `~/.k8s-mcp/state.json` on the machine running the MCP server. This includes:

- The full cluster config (all node IPs, SSH keys, settings)
- The kubeadm join command and certificate key
- Which Helm packages were successfully installed
- Credentials generated for installed applications (Jenkins, Grafana, Vault, etc.)
- Security configuration applied

When you close the `claude` terminal and reopen it, the state is automatically restored from disk. You do not need to re-run `plan_cluster`. The session continues exactly where you left it.

The state file is written with `chmod 600` (owner-readable only) and is located at:

```
~/.k8s-mcp/state.json    — current session state
~/.k8s-mcp/clusters.json — registry of all saved named clusters
~/.k8s-mcp/audit.log     — timestamped record of every tool call
```

#### `validate_config`

**What it does:** Validates a cluster config YAML file completely offline — no SSH, no servers required. Runs all checks that `plan_cluster` performs plus additional ones that are safe to check without live access.

**Checks performed:**
- All required fields present
- `cni`, `profile`, `monitoring` are valid supported values
- `k8s_version` is in `MAJOR.MINOR` format (e.g. `1.30`)
- `pod_cidr` and `service_cidr` are valid CIDR notation
- `pod_cidr` and `service_cidr` do not overlap each other
- Unusually small subnets flagged as warnings
- Node names are unique across masters and workers
- SSH key files exist at the specified paths on the local machine
- `proxy` block has at least one of `http_proxy` or `https_proxy` if present
- All `node_config` values are within supported options

**Output:** Reports errors (must fix) and warnings (review) separately. Clean configs show `VALIDATION PASSED`.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `config` | string | yes | Full YAML cluster config to validate |

**Example:**
```
You: Validate this config before I use it: [paste config]
Claude: [calls validate_config, finds no SSH key at ~/.ssh/id_rsa, reports as warning]
```

---

#### `save_cluster`

**What it does:** Gives the current session an explicit name and saves it to `~/.k8s-mcp/clusters.json`. Allows managing multiple clusters — each saved under a different name.

State is already auto-saved to disk on every tool call. `save_cluster` is the named, intentional checkpoint that lets you `switch_cluster` later.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | yes | Cluster name e.g. `prod`, `staging`, `dev` |

---

#### `switch_cluster`

**What it does:** Loads a previously saved cluster session and makes it the active one. All subsequent tool calls target the switched cluster.

Clears the current in-memory state and loads the saved config, installed packages list, application credentials, and security configuration for the target cluster.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | yes | Cluster name to switch to (must exist in `list_clusters`) |

---

#### `list_clusters`

**What it does:** Shows all saved cluster sessions with their details.

**Output per cluster:** name, K8s version, master/worker counts, profile, list of installed Helm packages, and when it was last saved. The currently active cluster is marked with ← ACTIVE.

**No parameters.**

---

#### `delete_cluster`

**What it does:** Removes a saved cluster session from the registry. Does NOT destroy the actual Kubernetes cluster — only removes the local session record.

To destroy the actual cluster first, use `destroy_cluster`, then `delete_cluster` to clean up the registry entry.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | yes | Cluster name to remove from registry |
| `confirm` | string | yes | Must be exactly `DELETE` |

---

#### `show_audit_log`

**What it does:** Shows the compliance audit trail — a timestamped record of every tool call made through this MCP server.

**What each entry contains:**
- Timestamp (ISO 8601)
- Cluster name (which cluster was being operated on)
- Tool name (which of the 41 tools was called)
- Parameters (with passwords, tokens, and keys automatically masked as `***`)
- Outcome (`started`, `success`, `error`, `exception`)
- A short note (e.g. `cluster=prod nodes=3`)

**Example output:**
```
2024-01-15T14:32:01  [prod-cluster]  plan_cluster     → success  (cluster=prod nodes=3)
2024-01-15T14:33:45  [prod-cluster]  prepare_nodes    → success  (installed=3)
2024-01-15T14:51:22  [prod-cluster]  bootstrap_cluster→ success  (masters=1 workers=2)
2024-01-15T15:02:11  [prod-cluster]  install_cni      → success
2024-01-15T15:18:44  [prod-cluster]  install_stack    → error    (helm repo add failed)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `lines` | integer | 50 | Number of recent entries to show |
| `cluster` | string | all | Filter by cluster name |
| `tool` | string | all | Filter by tool name |

**Full log path:** `~/.k8s-mcp/audit.log` on the machine running the MCP server.

---

#### `preflight_check`

**What it does:** SSHes into all nodes in parallel and verifies they are ready to be bootstrapped — before running `prepare_nodes`. Auto-fixes missing tools if `fix: true` (the default).

**Checks run on each node:**
- OS detection (reports which distro and family was found)
- Free disk space (warns if less than 20 GB free on `/`)
- RAM (warns if less than 2 GB available)
- Port availability: 6443, 10250, 2379, 2380 (warns if already in use)
- Swap status (warns if swap is active — kubeadm requires it disabled)
- Internet/proxy reachability (tests https://registry.k8s.io)
- Tool presence: `helm`, `etcdctl`, `kubectl`, `kubeadm`, `git`, `jq`

**Auto-fix:** When `fix: true` (default), any missing tool is installed immediately:
- `helm` — installed via the official get-helm-3 script
- `etcdctl` — binary downloaded from GitHub releases
- `git`, `jq` — installed via the node's package manager

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `fix` | boolean | true | Auto-install missing tools found during check |
| `node_name` | string | all nodes | Run on a specific node only |

---

## 10. Cluster profiles

A profile determines which Helm packages are installed when you run `install_stack`. You can always install additional packages later with `helm_manage` or `install_applications`.

| Profile | Installed packages | Typical use case |
|---------|-------------------|-----------------|
| `production` | ArgoCD, cert-manager, ingress-nginx, MetalLB, Velero | General-purpose production cluster |
| `development` | ArgoCD, ingress-nginx, cert-manager, Kubernetes Dashboard | Developer workstation or team dev cluster |
| `ml-gpu` | NVIDIA GPU Operator, Argo Workflows, Kubeflow Training Operator | Machine learning / model training cluster |
| `edge` | MetalLB, Longhorn | Lightweight cluster on edge hardware or IoT gateways |
| `multi-tenant` | ArgoCD, cert-manager, ingress-nginx, Capsule | Platform teams hosting multiple product teams |

**What each package does:**

| Package | What it does |
|---------|-------------|
| ArgoCD | Watches a Git repo and keeps the cluster in sync with the manifests in that repo (GitOps) |
| cert-manager | Automates issuance and renewal of TLS certificates from Let's Encrypt, your own CA, or self-signed |
| ingress-nginx | An HTTP reverse proxy that routes external traffic to services based on hostname and path rules |
| MetalLB | Provides LoadBalancer-type Service IPs on bare-metal — normally only available on cloud |
| Velero | Backup and restore tool for cluster resources and persistent volumes |
| NVIDIA GPU Operator | Installs and manages NVIDIA drivers, CUDA, and device plugins as containers |
| Argo Workflows | Kubernetes-native workflow engine for data pipelines and ML jobs |
| Kubeflow Training Operator | Manages distributed training jobs (TensorFlow, PyTorch) on Kubernetes |
| Longhorn | Distributed block storage — creates replicated volumes from the disks of your cluster nodes |
| Capsule | Multi-tenancy operator — creates Tenant objects that give teams isolated slices of the cluster |
| Kubernetes Dashboard | Browser-based cluster management UI |

---

## 11. CNI options

The CNI plugin handles pod networking — assigning IP addresses to pods and routing traffic between them.

| CNI | Architecture | Strengths | Consider when |
|-----|-------------|-----------|--------------|
| **Cilium** | eBPF-based (Linux kernel extension) | Highest performance, kube-proxy replacement, built-in observability (Hubble), L7 network policies | New clusters, modern kernel (5.10+), you want observability |
| **Calico** | iptables or eBPF, BGP routing support | Enterprise-grade, BGP peering with physical routers, fine-grained network policies | Enterprise networks with existing BGP infrastructure |
| **Flannel** | VXLAN overlay | Extremely simple, very low overhead | Simple networks, learning, small clusters |
| **Weave** | Mesh overlay | Simple, no external dependencies | Small teams, simple use case |

**Cilium defaults applied by this MCP:**
```
kubeProxyReplacement: true     — replaces kube-proxy with eBPF
ipam.mode: kubernetes          — uses K8s pod CIDR
hubble.relay.enabled: true     — enables the Hubble network observability relay
hubble.ui.enabled: true        — enables the Hubble browser UI
```

**Override any CNI value** via `cni_options` in your config.

---

## 12. Node configuration — kernel, sysctl, iptables, SELinux

Everything in this section is applied by `prepare_nodes` to every node before Kubernetes is bootstrapped.

### sysctl presets

`sysctl` parameters control kernel behaviour. Kubernetes requires specific values; production clusters benefit from additional tuning.

**k8s-minimal (3 parameters) — use for: development, testing, learning**
```
net.bridge.bridge-nf-call-iptables  = 1   # Required: iptables sees bridged traffic
net.bridge.bridge-nf-call-ip6tables = 1   # Required: same for IPv6
net.ipv4.ip_forward                 = 1   # Required: allows packet forwarding between interfaces
```

**k8s-production (13 parameters) — use for: general production workloads**
All of k8s-minimal plus:
```
net.ipv4.tcp_tw_reuse          = 1         # Reuse TIME_WAIT sockets faster (more connections/sec)
net.ipv4.ip_local_port_range   = 1024 65535 # More outbound ports available
net.core.somaxconn             = 32768      # Larger connection backlog per socket
net.core.netdev_max_backlog    = 16384      # Faster packet processing
fs.file-max                    = 1048576    # Maximum open file descriptors
fs.inotify.max_user_instances  = 8192       # Needed for many watchers (IDE, monitoring agents)
fs.inotify.max_user_watches    = 524288     # Needed for watching large source trees
kernel.pid_max                 = 65536      # More processes/threads
vm.swappiness                  = 0          # Never use swap unless absolutely necessary
vm.overcommit_memory           = 1          # Allow memory overcommit (used by many workloads)
```

**k8s-highperf (21 parameters) — use for: high-traffic, service meshes, API gateways**
All of k8s-production plus:
```
net.core.somaxconn             = 65535      # Larger connection backlog
net.core.netdev_max_backlog    = 65536      # Much faster packet processing
net.core.rmem_max              = 67108864   # 64MB receive buffer (for high-throughput)
net.core.wmem_max              = 67108864   # 64MB send buffer
net.ipv4.tcp_rmem              = 4096 87380 67108864  # TCP receive buffer range
net.ipv4.tcp_wmem              = 4096 65536 67108864  # TCP send buffer range
net.ipv4.tcp_syn_retries       = 2          # Faster failure on unreachable hosts
net.ipv4.tcp_synack_retries    = 2          # Faster failure on SYN flood
net.netfilter.nf_conntrack_max = 1048576    # Track 1M concurrent connections
vm.max_map_count               = 262144     # Required for Elasticsearch
fs.inotify.max_user_instances  = 16384      # More watcher instances
fs.inotify.max_user_watches    = 1048576    # 1M file watches
kernel.pid_max                 = 131072     # Double the pid limit
```

### Kernel modules

| Set | Modules loaded | Use when |
|-----|---------------|---------|
| `required` | overlay, br_netfilter | Always needed — minimum for kubeadm |
| `ipvs` | + ip_vs, ip_vs_rr, ip_vs_wrr, ip_vs_sh, nf_conntrack | Running kube-proxy in IPVS mode instead of iptables |
| `ipvs_legacy` | + ip_vs, ip_vs_rr, ip_vs_wrr, ip_vs_sh, nf_conntrack_ipv4 | Same but for kernels < 4.19 that use the old module name |
| `ebpf_extra` | + nf_conntrack | Cilium eBPF mode — needed on some kernel versions |
| `none` | overlay, br_netfilter (still loaded — these two are always required) | No extra modules needed |

Add anything custom in `extra_modules: [module-name, ...]`.

### SELinux (RHEL/CentOS/Rocky only)

| Setting | What happens on the node | When to use |
|---------|------------------------|------------|
| `permissive` | `setenforce 0` + `SELINUX=permissive` in `/etc/selinux/config` | Default safe choice — SELinux rules are logged but not enforced |
| `enforcing` | Nothing changed | When your CNI and container runtime are verified SELinux-compatible |
| `disabled` | `SELINUX=disabled` in config (takes effect after reboot) | When you need to disable entirely — least secure option |

### Swap

| Setting | What happens | When to use |
|---------|-------------|------------|
| `disable` | `swapoff -a` + comment out fstab entry | Default — permanent, survives reboot. kubeadm requires this by default. |
| `warn` | `swapoff -a` only (no fstab change) | When you cannot edit fstab but want to try the cluster. Swap re-enables on reboot. |
| `keep` | Nothing. | When you explicitly add `--fail-swap-on=false` to kubelet arguments yourself. |

---

## 13. Security layer

The security tools are installed and configured in a recommended sequence. Each step builds on the previous.

```
install_security_tools      — install Falco, Gatekeeper, Trivy Operator, Kyverno
       ↓
configure_rbac              — restrict default SAs, write audit policy
       ↓
configure_pod_security      — PSA admission mode + default-deny NetworkPolicy
       ↓
configure_etcd_encryption   — encrypt Secrets at rest
       ↓
configure_audit_logging     — API server audit log
       ↓
security_audit              — run compliance checks and get a report
```

You do not have to run all steps. Each is independent. Run only the ones that fit your requirements.

---

## 14. Applications

Applications are installed by `install_applications`. Credentials generated during installation are captured in session state and written to the cluster report.

**Access all applications via port-forward** (all are ClusterIP — no external exposure by default):

```bash
# Grafana (monitoring)
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80
# Jenkins
kubectl port-forward -n jenkins svc/jenkins 8080:8080
# SonarQube
kubectl port-forward -n sonarqube svc/sonarqube-sonarqube 9000:9000
# Harbor
kubectl port-forward -n harbor svc/harbor 8080:80
# Vault
kubectl port-forward -n vault svc/vault 8200:8200
# Keycloak
kubectl port-forward -n keycloak svc/keycloak 8080:80
```

**Default credentials (change these immediately):**

| Application | Default username | Default password |
|-------------|-----------------|-----------------|
| Grafana | `admin` | as set in `install_monitoring` call |
| Jenkins | `admin` | as set in `install_jenkins` call |
| SonarQube | `admin` | `admin` (change on first login) |
| Harbor | `admin` | retrieved from Kubernetes secret |
| Vault | — | root token is generated on init (shown once in output) |
| Keycloak | `admin` | retrieved from Kubernetes secret |

---

## 15. Certificates

This project handles certificates at two separate levels:

**Level 1 — Kubernetes control-plane certificates (managed by kubeadm)**
These are the TLS certificates that secure communication between Kubernetes components: API server ↔ etcd, API server ↔ kubelet, etc. They expire after 1 year by default (kubeadm renews them automatically on upgrade). Use `rotate_certs` to renew them manually.

**Level 2 — Workload certificates (managed by cert-manager)**
These are TLS certificates for your applications — ingress HTTPS, service-to-service mTLS, etc. cert-manager watches Certificate resources and renews them before they expire (typically at 2/3 of lifetime). Use `renew_service_cert` to force immediate renewal of any named Certificate.

**Zero-downtime renewal:**
- Control-plane: each master's kubelet is restarted sequentially — masters 2 and 3 (if HA) continue serving traffic while master 1 restarts
- Workload: cert-manager rotates the Secret in place; pods reload the new certificate from the mounted volume without restarting

---

## 16. Monitoring

**Prometheus stack (`prometheus` monitoring type):**
- Prometheus: time-series database and rule evaluator
- Grafana: visualisation dashboards (includes pre-built K8s dashboards)
- Alertmanager: notification routing (configure channels after install)

**Prometheus + Loki stack (`prometheus-loki` monitoring type):**
Everything above plus:
- Loki: horizontally scalable log aggregation system
- Promtail: agent running as a DaemonSet on every node, ships pod logs to Loki
- Grafana data source for Loki automatically configured

**Access Grafana:**
```bash
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80
# http://localhost:3000  —  admin / <password you set>
```

---

## 17. Cost reporting

`cost_report` reads live resource requests from the cluster and calculates an estimate. It does not read actual node capacity — it reads what applications have requested, which is a better proxy for actual usage.

**Default on-prem rates (edit these in your config):**
```
CPU:     $0.015 per vCPU per hour  → $10.95/vCPU/month
RAM:     $0.005 per GiB per hour   → $3.65/GiB/month
Storage: $0.10 per GiB per month
```

These are rough industry estimates. Adjust them to match your actual hardware costs (amortised server cost ÷ lifetime) for a meaningful number.

**For cloud providers:** The tool calculates cost from consumption × rates in the same way. Actual billing API integration requires cloud CLI credentials on the master node (AWS CLI, gcloud, az). The report will note the missing authentication and show the consumption-based estimate.

---

## 18. Cluster report output files

After running `generate_cluster_report`, two files appear on the master node at `/opt/cluster-report/<timestamp>/`:

**`cluster-report.md`** — Open in any Markdown viewer. Contains:
- All configuration settings
- Node and namespace lists
- All credentials in clearly labelled sections
- Compliance audit summary
- Cost estimate
- A checklist of next recommended actions

**`cluster-report.yaml`** — Structured data. Contains the same information in YAML format for automation, auditing tools, or import into a CMDB.

Both files are written with `chmod 600` (owner-readable only).

**⚠️ Credential rotation required after every report generation:**

Every time `generate_cluster_report` is called, the tool outputs a security notice listing which credentials to rotate and how. This is shown prominently in the conversation — do not skip it. The specific items to rotate after a new cluster setup:

| Service | How to rotate |
|---------|--------------|
| Grafana | `helm upgrade monitoring ... --set grafana.adminPassword=<new>` |
| Jenkins | Admin UI → Manage Jenkins → Security |
| SonarQube | Forced on first login by SonarQube itself |
| Harbor | Admin UI → Administration → Users |
| Vault root token | Use only for initial setup — revoke after configuring auth methods |
| Keycloak admin | Realm Settings → Users after first login |

The report file itself: do **not** commit it to any git repository. Do **not** share it over unencrypted channels. Delete it from the master node once you have retrieved and stored it securely (ideally: import credentials into Vault, then delete the file).

**Retrieve them:**
```bash
scp user@<master-ip>:/opt/cluster-report/*/cluster-report.md ./
scp user@<master-ip>:/opt/cluster-report/*/cluster-report.yaml ./
```

---

## 19. Operating systems supported

| OS family | Distros tested | Package manager | Python 3.10+ source |
|-----------|---------------|----------------|---------------------|
| `debian` | Ubuntu 20.04, 22.04, 24.04 / Debian 10, 11, 12 | `apt` | `apt install python3.11` |
| `rhel` | RHEL 8+, Rocky Linux 8+, AlmaLinux 8+, CentOS Stream 8+ | `dnf` or `yum` | `dnf install python3.11` |
| `suse` | SLES 15+, openSUSE Leap 15+ | `zypper` | `zypper install python311` |

**Mixed-OS clusters are fully supported.** The master can be RHEL and the workers can be Ubuntu. Each node is detected independently during `prepare_nodes` and gets the script for its OS family.

**Explicit override** — set `os_family: rhel` on a node entry to skip auto-detection. Useful when a node's `/etc/os-release` returns an unusual ID.

---

## 20. Corporate proxy support

If your servers connect to the internet through a corporate proxy, add a `proxy:` block at the top level of your cluster config. Remove this block entirely if servers have direct internet access — it adds no overhead when absent.

```yaml
proxy:
  http_proxy:  "http://proxy.corp.local:3128"
  https_proxy: "http://proxy.corp.local:3128"
  no_proxy:    "localhost,127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.svc,.cluster.local,.corp.local"
```

**Where the proxy is applied:**

| Scope | Mechanism |
|-------|-----------|
| Shell commands (curl, etc.) | `export http_proxy=... https_proxy=... HTTP_PROXY=... HTTPS_PROXY=... no_proxy=... NO_PROXY=...` |
| apt (Debian) | `/etc/apt/apt.conf.d/95proxies` file |
| dnf/yum (RHEL) | `proxy=` line appended to `/etc/dnf/dnf.conf` or `/etc/yum.conf` |
| containerd | `/etc/systemd/system/containerd.service.d/http-proxy.conf` (systemd unit drop-in) |
| helm | Shell env vars (helm reads them natively) |
| kubectl apply -f | Shell env vars |
| Upgrades and scale operations | Re-applied automatically on every operation that touches packages |

**Why containerd needs a separate drop-in:** containerd is a systemd daemon. Daemons do not inherit environment variables from the shell session that started them — they read their environment from systemd unit files. Writing a drop-in to `/etc/systemd/system/containerd.service.d/` and reloading systemd is the correct way to set environment variables for systemd-managed services.

---

## 21. Multi-master HA

To create a highly-available control plane, list 3 masters in your config (3 is the minimum for etcd quorum — 2 masters can lose only 0 nodes before losing quorum, while 3 can lose 1 node):

```yaml
masters:
  - name: master-1
    ip: 192.168.1.10
    user: ubuntu
    ssh_key: ~/.ssh/id_rsa
  - name: master-2
    ip: 192.168.1.11
    user: ubuntu
    ssh_key: ~/.ssh/id_rsa
  - name: master-3
    ip: 192.168.1.12
    user: ubuntu
    ssh_key: ~/.ssh/id_rsa
```

**What happens during bootstrap:**
1. `kubeadm init --upload-certs` runs on master-1. This generates a certificate key and uploads the control-plane certificates to a cluster Secret.
2. The certificate key and the worker join command are captured.
3. master-2 runs `kubeadm join --control-plane --certificate-key <key>`. It downloads the certificates from the Secret and joins as a control-plane node.
4. master-3 does the same.
5. Workers run the standard `kubeadm join` (no `--control-plane`).

**HA note:** This creates a stacked HA setup — etcd runs on the same nodes as the control plane. For external etcd topology (etcd on separate machines), that is a future feature.

**No VIP is automatically created.** The `control_plane_endpoint` defaults to the first master's IP. For true HA you need a virtual IP (VIP) in front of all masters. kube-vip is the recommended solution for bare-metal VIP — see the TODO in this project for the planned `install_kubevip` tool.

---

## 22. Workflow walkthrough — zero to running cluster

This is the full recommended sequence for a new production cluster.

```
Step 1:  Write cluster_config.yaml   (use an example from examples/ as a starting point)
Step 2:  validate_config             Offline validation — catch errors before touching servers
Step 3:  claude mcp list             (confirm k8s-factory is connected)
Step 4:  claude                      (start a session)

── In the session ──────────────────────────────────────────────────────────────

Step 5:  plan_cluster                Review plan, node_config defaults, proxy status
Step 6:  preflight_check             Verify all nodes: disk, RAM, ports, tools — auto-fix
Step 7:  prepare_nodes dry_run       See the exact script before it runs
Step 8:  prepare_nodes               OS detected, containerd and kubeadm installed
Step 9:  bootstrap_cluster           Kubernetes control plane + worker joins
                                     (idempotent — safe to re-run if partially failed)
Step 10: install_cni                 Nodes go Ready
Step 11: cluster_status              Confirm all nodes Ready, system pods Running

Step 12: install_stack               Profile packages (resume-from-failure if interrupted)
Step 13: install_monitoring          Prometheus + Grafana (or + Loki)
Step 14: install_cert_manager        cert-manager + ClusterIssuer
Step 15: install_jenkins             Jenkins CI/CD (if needed)
Step 16: install_security_tools      Falco, Gatekeeper, Trivy, Kyverno (choose any)
Step 17: install_applications        SonarQube, Harbor, Vault, Keycloak (choose any)

Step 18: configure_rbac              Restrict default SAs, write audit policy
Step 19: configure_pod_security      PSA mode + default-deny NetworkPolicy
Step 20: configure_etcd_encryption   Encrypt secrets at rest
Step 21: configure_audit_logging     API server audit log

Step 22: provision_namespace         Create a namespace for your first team
Step 23: manage_kubeconfig           Give them a scoped kubeconfig

Step 24: backup_etcd                 Take the first backup
Step 25: security_audit              Baseline compliance check (CIS + NSA + PCI + SOC2)
Step 26: cost_report                 Resource consumption and cost estimate
Step 27: generate_cluster_report     Write Markdown + YAML report (read the rotation warning!)

Step 28: save_cluster                Save the session as "prod" (or your cluster name)
Step 29: show_audit_log              Review every action taken during setup
Step 30: scp the report files off    Save them securely — delete from master after
```

You do not have to do all 30 steps in one session. Session state is automatically
saved to `~/.k8s-mcp/state.json` after every successful tool call — closing the
terminal does not lose your progress. Reopen `claude` and continue where you left off.

For multiple clusters: use `save_cluster` to name each session, and `switch_cluster`
to move between them. `list_clusters` shows all saved sessions.

---

## 23. Compliance standards

### CIS Kubernetes Benchmark (9 checks)

The CIS Benchmark is maintained by the Center for Internet Security and is the most widely adopted Kubernetes security standard.

| Check ID | What is checked |
|----------|----------------|
| CIS 1.1.1 | kube-apiserver pod spec file has restrictive permissions |
| CIS 1.2.1 | `--anonymous-auth=false` is set on the API server |
| CIS 1.2.6 | `--insecure-port=0` (insecure port disabled) |
| CIS 1.2.9 | Admission plugins are configured |
| CIS 2.1 | etcd peer TLS certificates are configured |
| CIS 4.2.1 | kubelet anonymous authentication is disabled |
| CIS 5.1.3 | No ClusterRoles with wildcard verbs (`*`) |
| CIS 5.2.2 | No privileged containers running |
| CIS 5.7.1 | Namespaces have NetworkPolicies defined |

### NSA/CISA Kubernetes Hardening Guide (5 checks)

Published by the US National Security Agency and Cybersecurity and Infrastructure Security Agency.

| Check | What is checked |
|-------|----------------|
| NSA 1 | Containers do not run as root |
| NSA 2 | Root filesystems are read-only |
| NSA 3 | `allowPrivilegeEscalation: false` on all containers |
| NSA 4 | All containers have CPU and memory limits |
| NSA 5 | No hostPath volumes mounting sensitive paths (`/etc`, `/proc`, `/sys`, `/dev`, docker socket) |

### PCI-DSS (4 checks)

Payment Card Industry Data Security Standard.

| Check | What is checked |
|-------|----------------|
| PCI DSS 6.3 | Default ServiceAccount tokens not automounted |
| PCI DSS 7.1 | No ClusterRoleBindings binding cluster-admin to human users |
| PCI DSS 8.2 | Each workload uses a dedicated ServiceAccount (not `default`) |
| PCI DSS 10.1 | API server audit logging is enabled |

### SOC2 / ISO27001 (5 checks)

Controls aligned to SOC2 Trust Services Criteria and ISO 27001 Annex A.

| Check | What is checked |
|-------|----------------|
| SOC2 | No passwords, tokens, or keys in container environment variables |
| SOC2 | No `latest` image tags (traceability) |
| ISO27001 A.12.6 | Trivy Operator is installed (vulnerability management) |
| ISO27001 A.9 | RBAC is enabled (access control) |
| ISO27001 A.10 | etcd encryption is configured (cryptographic controls) |

---

## 24. Troubleshooting

### MCP server won't start

```bash
# Run directly to see the error
python3 ~/mcp-servers/k8s_factory_mcp.py
```

| Error | Fix |
|-------|-----|
| `No module named 'mcp'` | `pip install mcp --break-system-packages` |
| `No module named 'paramiko'` | `pip install paramiko --break-system-packages` |
| `SyntaxError: invalid syntax` | Your Python is < 3.10. Install 3.11: `dnf install python3.11` |

### prepare_nodes fails on a node

1. Check that you can SSH manually: `ssh user@node-ip`
2. Check that the user has sudo rights: `sudo -l` on the node
3. Run with `dry_run: true` and inspect the generated script
4. Run `node_diagnostics` on the failing node to check disk space and network

### kubeadm init fails

Common causes:
- Not enough memory (needs ≥ 2GB RAM)
- Swap is still enabled (`free -h` on the node — should show 0 swap)
- A previous kubeadm cluster state exists (run `destroy_cluster` first)
- Pod CIDR overlaps with node subnet

### Nodes stay NotReady

The CNI is not installed yet (or failed to install). Run `install_cni` or check `kubectl get pods -n kube-system` for CNI pods in Error state.

### Helm installs fail with network errors

If using a proxy: confirm the `proxy:` block is in your config and the proxy URL is reachable from the nodes. Test: `curl -x http://proxy:3128 https://charts.helm.sh` on a node.

If direct internet: confirm the nodes can reach `registry.k8s.io`, `charts.helm.sh`, and the Helm chart repos.

### Session state after terminal restart

Session state is automatically saved to `~/.k8s-mcp/state.json` after every successful tool call. If you close the terminal and reopen it, the state is restored automatically — you do not need to re-run `plan_cluster`.

To confirm the state was restored, run `list_clusters` or `cluster_status` immediately after reopening the session. If the state is missing (e.g. on a fresh machine), re-run `plan_cluster` with the same config to restore it.

For intentional multi-cluster management: `save_cluster prod`, `save_cluster staging`, then `switch_cluster prod` and `switch_cluster staging` to move between them cleanly.

### install_stack partially failed (some packages failed, some succeeded)

Re-run `install_stack` — it tracks which releases were successfully installed and skips them, retrying only the ones that failed. You will see `[SKIP]` lines for already-installed packages and the retry only applies to the failures.

---

## 25. Contributing

The project is tagged as `k8s-mcp-v1`. Contributions are welcome.

**To add a new tool:**
1. Add a constant block near the top if the tool needs its own Helm chart config or option list
2. Add a `Tool(...)` entry in `list_tools()`
3. Add a handler branch in `call_tool()`
4. Add an entry in `NEXT_STEPS` for the tool and for the tools that lead to it
5. Run `python3 -W error -c "import ast; ast.parse(open('k8s_factory_mcp.py').read())"` to verify syntax
6. Update `TODO.md` — move the item from the to-do section to the implemented section
7. Add an example config to `examples/` if relevant

**To add a new OS family:**
1. Add an entry to `PKG_COMMANDS` following the existing pattern
2. Add the detection logic in `detect_os_family()` to map `/etc/os-release` ID values to the new family
3. Update `SUPPORTED_OS_FAMILIES`

**To add a new compliance standard:**
1. Add a key to `COMPLIANCE_CHECKS` with a list of `(label, shell_command)` tuples
2. Add the key to `SUPPORTED_COMPLIANCE`
3. The `security_audit` tool picks it up automatically

---

## 26. Glossary

| Term | Definition |
|------|-----------|
| **CNI** | Container Network Interface — the plugin that handles pod IP assignment and network routing |
| **CRI** | Container Runtime Interface — the plugin that runs containers. containerd and CRI-O are the main options |
| **etcd** | The distributed key-value store that holds all Kubernetes cluster state |
| **HPA** | HorizontalPodAutoscaler — scales the number of pod replicas based on CPU/memory metrics |
| **kube-proxy** | The network proxy that implements Service VIPs (can be replaced by Cilium eBPF) |
| **kubeadm** | The official tool for bootstrapping and managing the Kubernetes control plane |
| **kubeconfig** | A YAML file containing the cluster endpoint, CA cert, and user credentials for kubectl |
| **kubelet** | The agent running on every node, responsible for starting and monitoring pods |
| **LimitRange** | A namespace-level resource that sets default CPU/memory requests and limits for containers |
| **MCP** | Model Context Protocol — Anthropic's standard for letting Claude AI call external tools |
| **MetalLB** | A load balancer for bare-metal Kubernetes that assigns real IP addresses to LoadBalancer services |
| **OIDC** | OpenID Connect — an authentication protocol built on OAuth 2.0, used by Keycloak and others |
| **OPA** | Open Policy Agent — a general-purpose policy engine used by Gatekeeper |
| **PDB** | PodDisruptionBudget — guarantees a minimum number of pods remain available during voluntary disruptions |
| **PVC** | PersistentVolumeClaim — a request for storage by a pod |
| **RBAC** | Role-Based Access Control — Kubernetes' permission system |
| **ResourceQuota** | A namespace-level resource that caps total CPU, memory, and object counts |
| **SAST** | Static Application Security Testing — scanning source code for security vulnerabilities |
| **SELinux** | Security-Enhanced Linux — a mandatory access control system enforced by the kernel |
| **ServiceAccount** | A Kubernetes identity for processes running inside pods |
| **sysctl** | Linux kernel parameter interface — controls networking, file system, and memory behaviour |
| **VIP** | Virtual IP address — a single IP backed by multiple servers for HA |

---

## 27. Setting up the executor node — step by step

The **executor node** is the machine that runs the MCP server (`k8s_factory_mcp.py`) and the `claude` CLI. It is the machine that SSHes into your cluster nodes. It does not need to be one of your cluster nodes — it can be a separate jump host, bastion, or one of the cluster nodes acting double-duty.

This section covers every scenario: access from a laptop with direct SSH, access from inside an OpenStack environment via the Horizon browser console, and RHEL 8.6 (the exact environment this project was tested on).

---

### Scenario A — Your laptop has direct SSH access to the cluster nodes

This is the simplest case. Run everything on your laptop.

#### Step 1 — Check your Python version

```bash
python3 --version
```

You need Python 3.10 or newer. If you have Python 3.6 or 3.8, install 3.11 alongside it (see Scenario C for RHEL-specific steps).

#### Step 2 — Install dependencies

```bash
pip install mcp paramiko pyyaml --break-system-packages
```

Verify:
```bash
python3 -c "import mcp, paramiko, yaml; print('all OK')"
```

#### Step 3 — Install Claude Code

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

Claude Code will print an authentication URL on first run. Open it in your browser and log in with your Anthropic account. The token is stored locally and you will not be asked again.

```bash
claude --version
```

#### Step 4 — Save the MCP server file

```bash
mkdir -p ~/mcp-servers
cp k8s_factory_mcp.py ~/mcp-servers/k8s_factory_mcp.py
```

#### Step 5 — Register with Claude Code

```bash
claude mcp add k8s-factory -- python3 ~/mcp-servers/k8s_factory_mcp.py
claude mcp list
```

Expected output: `k8s-factory    connected`

#### Step 6 — Test SSH to your nodes manually

Before starting a Claude session, confirm SSH works:
```bash
ssh user@<master-ip> echo "SSH OK"
ssh user@<worker-1-ip> echo "SSH OK"
ssh user@<worker-2-ip> echo "SSH OK"
```

If any of these fail, fix SSH access before proceeding. Every tool in this MCP uses the same SSH path.

#### Step 7 — Start a session and load the tools

```bash
claude
```

Inside the session:
```
> /mcp
```

You should see `k8s-factory` with 34 tools listed. You are ready.

---

### Scenario B — You are inside an OpenStack environment with only Horizon web console access

This applies when your cluster nodes are on an isolated OpenStack tenant network with no floating IPs reachable from outside, and your only access is through the OpenStack Horizon browser-based VNC console.

In this scenario, one of your cluster nodes (typically `master-1`) becomes the executor node.

#### Step 1 — Open the Horizon console

In the OpenStack Horizon dashboard:

```
Compute → Instances → <your-master-1> → Console tab
```

You now have a browser-based terminal. Log in with the node's username and password (or set a password first via the metadata if the instance only has key auth — check with your OpenStack administrator).

#### Step 2 — Set a password if needed (for console login)

If the console shows a login prompt and you only have an SSH key:
```bash
# From a machine that can SSH in temporarily:
ssh user@<floating-ip-if-available>
sudo passwd ubuntu    # or whatever your username is
```

Or ask your OpenStack admin to inject a password via the instance metadata.

#### Step 3 — Check OS and internet access

Inside the Horizon console on master-1:
```bash
cat /etc/os-release          # confirm OS family
python3 --version            # check Python version
curl -I https://pypi.org     # test internet (or proxy) access
```

If `curl` fails, you are behind a proxy. Get the proxy URL from your network team and set it:
```bash
export http_proxy="http://proxy.corp.local:3128"
export https_proxy="http://proxy.corp.local:3128"
```

#### Step 4 — Fix dnf repos if needed (RHEL/CentOS 8 only)

If you see `Cannot prepare internal mirrorlist` errors on CentOS 8:
```bash
sudo sed -i 's/mirrorlist/#mirrorlist/g' /etc/yum.repos.d/CentOS-*
sudo sed -i 's|#baseurl=http://mirror.centos.org|baseurl=http://vault.centos.org|g' /etc/yum.repos.d/CentOS-*
sudo dnf update -y
```

For RHEL 8 that is not yet registered:
```bash
sudo subscription-manager register --org="<org-id>" --activationkey="<key>"
sudo subscription-manager attach --auto
```

#### Step 5 — Install Python 3.11

On RHEL/CentOS/Rocky/Alma:
```bash
sudo dnf install -y python3.11 python3.11-pip
python3.11 --version
```

On Ubuntu/Debian:
```bash
sudo apt-get update && sudo apt-get install -y python3.11 python3.11-pip
python3.11 --version
```

#### Step 6 — Get the MCP server file onto the executor node

**Option A — git clone (if GitHub/GitLab is reachable):**
```bash
sudo dnf install -y git      # or apt-get install git
git clone https://github.com/<your-org>/k8s-mcp-v1.git
cd k8s-mcp-v1
```

**Option B — paste via base64 (no git, no SCP — Horizon console only):**

On your local machine:
```bash
base64 -w0 k8s_factory_mcp.py
# This prints one very long line
```

Copy the entire output, then in the Horizon console:
```bash
cat > /tmp/k8s_factory_mcp.b64
# Paste the base64 line, then press Enter, then Ctrl+D
base64 -d /tmp/k8s_factory_mcp.b64 > ~/k8s_factory_mcp.py
wc -l ~/k8s_factory_mcp.py    # should show ~3292
```

**Option C — internal file server (if your org has Nexus/Artifactory/internal HTTP):**
```bash
wget http://internal-server/k8s_factory_mcp.py -O ~/k8s_factory_mcp.py
```

#### Step 7 — Install Python dependencies

```bash
python3.11 -m pip install mcp paramiko pyyaml
```

If behind a proxy:
```bash
python3.11 -m pip install --proxy http://proxy.corp.local:3128 mcp paramiko pyyaml
```

Verify:
```bash
python3.11 -c "import mcp, paramiko, yaml; print('all OK')"
```

#### Step 8 — Install Claude Code

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

If behind a proxy:
```bash
http_proxy="http://proxy.corp.local:3128" https_proxy="http://proxy.corp.local:3128" \
  curl -fsSL https://claude.ai/install.sh | bash
```

#### Step 9 — Authenticate Claude Code (the key step for console-only access)

Run:
```bash
claude
```

Claude Code prints an authentication URL like:
```
Please visit this URL to authenticate:
https://claude.ai/auth/...
```

**Copy that URL.** Open it in a browser on your laptop (or any machine with a browser). Complete the login. The session token is saved on the executor node (master-1). You do not need a browser on the executor node itself — just a way to visit the URL once.

After authenticating, Claude Code on master-1 is ready.

#### Step 10 — Install tmux to survive console disconnects

The Horizon console connection can drop. tmux keeps your Claude session alive:
```bash
sudo dnf install -y tmux     # or apt-get install tmux
tmux new-session -s k8s
```

All work from this point happens inside the tmux session. If the console drops, reconnect and run:
```bash
tmux attach -t k8s
```

Your session and all session state (cluster config, credentials) will be exactly where you left it.

#### Step 11 — Set up SSH key from master-1 to other nodes

Since master-1 is now the executor, it needs SSH access to worker-1 and worker-2 (and to itself, for the cluster config).

```bash
# Generate an SSH key on master-1 if one doesn't exist
ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N ""
cat ~/.ssh/id_rsa.pub
```

Copy the output public key. For each other node (worker-1, worker-2), open its Horizon console and run:
```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "PASTE_PUBLIC_KEY_HERE" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Also add the key to master-1's own authorized_keys (so it can SSH to itself):
```bash
cat ~/.ssh/id_rsa.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Test:
```bash
ssh ubuntu@<worker-1-internal-ip> echo "SSH OK"
ssh ubuntu@<worker-2-internal-ip> echo "SSH OK"
ssh ubuntu@<master-1-internal-ip> echo "SSH OK"
```

Use **internal IPs** (not floating IPs) — all nodes are on the same OpenStack tenant network.

#### Step 12 — Register the MCP server and start

```bash
# Inside tmux, inside the claude session:
claude mcp add k8s-factory -- python3.11 ~/k8s_factory_mcp.py
claude mcp list   # confirm: connected
claude            # start a session
```

---

### Scenario C — RHEL 8.6 executor node (detailed)

RHEL 8.6 ships with Python 3.6 as the system default. Python 3.6 is too old for the `mcp` package. These steps install Python 3.11 alongside the system Python without touching the system Python.

#### Step 1 — Confirm the problem

```bash
python3 --version    # shows 3.6.x
pip3 install mcp     # will fail: "no matching distribution found"
```

#### Step 2 — Check subscription status

```bash
sudo subscription-manager status
sudo dnf repolist
```

If `subscription-manager status` shows `Unknown` or `Invalid`, the system is not registered to Red Hat. Without a valid subscription, the RHEL repos return 404 and `dnf install` fails with network errors (which you might mistake for Python version errors).

Register with your organization's Red Hat Satellite or Red Hat Customer Portal:
```bash
# With Satellite (common in corporate environments):
sudo subscription-manager register \
  --org="<your-org-id>" \
  --activationkey="<your-activation-key>"

# With Red Hat directly:
sudo subscription-manager register \
  --username=<your-rh-username> \
  --password=<your-rh-password>
sudo subscription-manager attach --auto
```

If behind a proxy, register that first:
```bash
sudo subscription-manager config \
  --server.proxy_hostname=proxy.corp.local \
  --server.proxy_port=3128
```

#### Step 3 — Install Python 3.11

Once the repos work:
```bash
sudo dnf install -y python3.11 python3.11-pip
python3.11 --version    # should show 3.11.x
```

If `python3.11` is not in the standard repos, enable the AppStream module:
```bash
sudo dnf module enable -y python311
sudo dnf install -y python3.11 python3.11-pip
```

#### Step 4 — Install dependencies with the correct Python

```bash
python3.11 -m pip install --upgrade pip
python3.11 -m pip install mcp paramiko pyyaml
```

#### Step 5 — Install Claude Code

```bash
# Standard install
curl -fsSL https://claude.ai/install.sh | bash

# If behind proxy:
http_proxy="http://proxy:3128" https_proxy="http://proxy:3128" \
  curl -fsSL https://claude.ai/install.sh | bash
```

If `curl` itself is not installed:
```bash
sudo dnf install -y curl
```

#### Step 6 — Register with the correct Python

When registering the MCP server, always specify the full Python 3.11 path:
```bash
claude mcp add k8s-factory -- python3.11 ~/mcp-servers/k8s_factory_mcp.py
```

If you used the system `python3` instead and get a `No module named mcp` error, remove and re-add:
```bash
claude mcp remove k8s-factory
claude mcp add k8s-factory -- python3.11 ~/mcp-servers/k8s_factory_mcp.py
```

---

### Verifying everything is working

Run this inside a `claude` session to confirm all 34 tools are available:
```
> /mcp
```

You should see `k8s-factory` with 34 tools. If you see fewer, the server loaded but some tools failed to parse — run `python3.11 ~/mcp-servers/k8s_factory_mcp.py` directly to see the error.

---

## 28. Example prompts — how to talk to Claude

The MCP server works by having a natural conversation. You do not need to know the tool names or parameter names — Claude will call the right tool and ask for any missing information. This section shows example prompts for every major capability, from basic to complex.

---

### Starting a cluster

**Basic:**
```
Plan a Kubernetes cluster for my 3 OpenStack VMs:
- master-1: 10.0.0.10, ubuntu, ~/.ssh/id_rsa
- worker-1: 10.0.0.20, ubuntu, ~/.ssh/id_rsa
- worker-2: 10.0.0.21, ubuntu, ~/.ssh/id_rsa
```

**With full configuration choices:**
```
I want to create a production Kubernetes cluster on 3 servers.
Master: 10.0.0.10, Workers: 10.0.0.20 and 10.0.0.21
All Ubuntu 22.04, user=ubuntu, key=~/.ssh/id_rsa
I want: Cilium CNI, production profile, Prometheus+Loki monitoring.
My servers go through a proxy: http://proxy.corp:3128
For sysctl use the production preset.
Disable SELinux on RHEL nodes and disable swap permanently.
Plan it for me and show me what will be configured.
```

**Asking Claude to guide you (no config knowledge needed):**
```
I have 3 Linux servers and I want to set up Kubernetes on them.
I've never done this before. Can you ask me what you need?
```
Claude will ask you for IPs, SSH details, and guide you through every choice.

---

### Cluster status with resource details

```
Show me the status of the prod cluster — I want to see all nodes,
which pods are unhealthy, and what storage is in use.
```

```
Give me a health check of the cluster including how much storage
is being used and which nodes have the most pods running.
```

```
Check if there are any pods that are not running and tell me
which namespace they are in and what the error is.
```

---

### Cluster status with costing

```
Show me the cluster status and also tell me what this cluster
is costing per month. We pay $0.02 per vCPU per hour and
$0.006 per GB of RAM per hour.
```

```
Run a full health check on the cluster, then give me a breakdown
of resource usage and estimated monthly cost per namespace.
I'm on OpenStack, rates: CPU $0.015/core/hr, RAM $0.005/GB/hr,
storage $0.08/GB/month.
```

```
What is the most expensive namespace in the cluster right now?
Show me resource requests, limits, and estimated cost for each namespace.
```

---

### Upgrading etcd without downtime

```
I need to upgrade etcd. Walk me through doing it without any downtime.
```

Claude will ask about your current version and target version, then explain that etcd itself is managed by kubeadm and the upgrade path goes through `upgrade_cluster`. It will explain the process:

```
We need to upgrade the Kubernetes control plane from 1.29 to 1.30.
This upgrades etcd, the API server, scheduler, and controller manager
together. Show me a dry run first, then proceed with the upgrade.
```

For etcd backup before upgrading (always recommended):
```
Before we upgrade, take an etcd backup, then do a rolling control-plane
upgrade from 1.29 to 1.30 with no downtime. Walk me through each step.
```

---

### Upgrading the cluster

```
Upgrade the cluster to Kubernetes 1.31. Do it without taking
the cluster down — applications should keep running throughout.
Show me a dry run first.
```

```
I need to upgrade one worker node at a time. Can you upgrade
worker-1 first, verify it came back healthy, then do worker-2?
```

```
Do a rolling cluster upgrade to 1.31. After the upgrade, check
the cluster status and rotate the certificates since they expire
in 3 months anyway.
```

---

### Security setup

**Quick security scan:**
```
Run a security audit on the cluster against the CIS Kubernetes
Benchmark and tell me what I need to fix.
```

**Full compliance sweep:**
```
Run a compliance audit against all four standards: CIS, NSA/CISA,
PCI-DSS, and SOC2/ISO27001. Show me pass/fail for each control
and tell me which findings are the most critical to fix first.
```

**Step-by-step hardening:**
```
I want to harden this cluster for production. Walk me through
the full security setup: RBAC restrictions, Pod Security Admission,
etcd encryption, and audit logging. Ask me about any choices
I need to make along the way.
```

**Installing security tools:**
```
Install Falco and the Trivy Operator on the cluster.
I want runtime threat detection and image vulnerability scanning.
Tell me what each one does before installing.
```

---

### Installing applications

**One at a time:**
```
Install SonarQube on the cluster. Use Longhorn storage.
What are the admin credentials once it's installed?
```

**Full DevOps stack:**
```
I want to set up a complete DevOps toolchain on this cluster.
Install Jenkins, SonarQube, and Harbor. Use the default StorageClass
for all of them. Show me the credentials and how to access each one.
```

**Secrets management:**
```
Install HashiCorp Vault on the cluster and configure it
so that pods can authenticate to Vault using their Kubernetes
ServiceAccount tokens. Show me the unseal keys and root token.
```

**SSO setup:**
```
Install Keycloak for SSO. I want the cluster's API server to use
it for user authentication so my team can log in with their
company credentials. Set admin password to "TempPass2024".
```

---

### Certificate management

**Check what certificates exist and when they expire:**
```
Check all the Kubernetes control-plane certificate expiry dates.
Also show me the cert-manager certificates if any are installed.
```

**Renew control-plane certs with no downtime:**
```
Renew all the kubeadm certificates on the cluster. I have
3 masters so do it with no downtime — renew them one at a time.
```

**Set up automated certificate management:**
```
Install cert-manager with a self-signed cluster CA.
I don't have external DNS or Let's Encrypt access.
Then show me how to renew any application certificate on demand.
```

**Renew a specific service certificate:**
```
The certificate for the ingress on the payments namespace is
expiring in 2 weeks. Trigger a renewal for it now without
restarting any pods.
```

---

### Scaling

**Add a worker node:**
```
I have a new server at 10.0.0.30 that I want to add to the cluster
as a worker. It's Ubuntu 22.04, user=ubuntu, key=~/.ssh/id_rsa.
Add it and confirm it joined successfully.
```

**Add a master for HA:**
```
The cluster currently has 1 master. I want to add 2 more masters
for HA — they're at 10.0.0.11 and 10.0.0.12.
Both are RHEL 8, user=centos, key=~/.ssh/id_rsa.
Add them as control-plane nodes.
```

**Remove a node gracefully:**
```
Drain worker-2 and remove it from the cluster.
Make sure all its pods are rescheduled before removing it.
```

---

### Backups and recovery

**Take a backup:**
```
Take an etcd backup now. Save it to /backups/etcd on the master.
```

**Before a risky change:**
```
Before we do the upgrade, take an etcd backup and also export
a snapshot of all cluster resources to /opt/snapshots.
Then proceed with the upgrade.
```

**Test the recovery path:**
```
List the etcd backups available on the master.
Then show me how to restore from the most recent one
(don't actually do it — just show me the dry run so I know
the process works).
```

---

### Namespaces and access control

**Onboard a team:**
```
Create a namespace called "payments" for the payments team.
Give them 4 CPUs and 8GB of memory total.
Then generate a kubeconfig file for them with edit permissions.
```

**Full team onboarding:**
```
The frontend team needs their own namespace.
Create a namespace "frontend" with: 8 CPU limit, 16Gi memory.
Set up a default-deny NetworkPolicy.
Generate a kubeconfig with admin access.
Tell me how to give it to them.
```

---

### Monitoring

**Set up monitoring:**
```
Install Prometheus and Grafana on the cluster.
Set the Grafana password to "MyGrafana2024".
Tell me how to access the dashboard.
```

**Set up monitoring with log aggregation:**
```
Install the full monitoring stack including Loki for log aggregation.
I want to be able to search pod logs from the Grafana UI.
```

**Check monitoring after setup:**
```
Is Prometheus scraping all nodes? Show me the monitoring pod status
and tell me how to verify that Alertmanager is configured.
```

---

### Workload migration

**Migrate docker-compose:**
```
Convert this docker-compose.yml to Kubernetes manifests.
I want it in the "backend" namespace with 2 replicas.
Also add auto-scaling so it scales to 10 replicas when CPU hits 70%.

[paste docker-compose.yml here]
```

**Full migration with guidance:**
```
Here is my docker-compose file for a 3-service application:
web (nginx), api (node), db (postgres). I want to migrate all
3 services to Kubernetes. What do I need to set up first
(storage, namespaces, etc.) before deploying?

[paste docker-compose.yml here]
```

---

### Generating the cluster report

**Full report:**
```
Generate the full cluster report. Include all credentials,
service IPs, namespaces, certificate expiry dates, and the
cost estimate. Save it as both Markdown and YAML.
```

**Report without secrets (for sharing):**
```
Generate a cluster report that I can share with my manager.
Leave out the actual credential values — just show the
service names and access instructions.
```

**After everything is set up:**
```
We've finished setting up the cluster. Generate the full report
including security audit results and cost estimate, then tell me
how to copy the files off the master node.
```

---

### Troubleshooting

**A pod is not starting:**
```
The payment-api pod in the payments namespace is stuck in
CrashLoopBackOff. Show me the logs — including the previous
container's logs — and run diagnostics on the node it's on.
```

**A node is having problems:**
```
worker-2 is showing high load and some pods are being evicted.
Run full diagnostics on it: check disk, memory, CPU, OOM events,
and kubelet logs.
```

**Cluster feels slow:**
```
The cluster feels slow today. Check the health of all nodes,
look for any pods stuck in unusual states, and show me resource
usage across all namespaces so I can see what's consuming the most.
```

**After an incident:**
```
We had a production incident last night. The API server was
unreachable for 10 minutes. Run a full security audit, check
the audit logs configuration, and show me what is currently
in the kube-system pod list. I want to understand what happened.
```

---

### Combining tools in one conversation

One of the key advantages of the MCP approach is that you can chain multiple operations in a single conversation:

```
Do the following in order:
1. Check cluster status
2. Run a cost report broken down by namespace
3. Run a CIS security audit
4. Generate the full cluster report with everything
Tell me if anything looks wrong at each step before continuing.
```

```
Set up a complete DevOps environment on this cluster:
1. Install Jenkins with 20Gi storage
2. Install SonarQube
3. Install Harbor registry
4. Install Falco for runtime security
5. Set up monitoring with Prometheus and Loki
6. Create a namespace "cicd" for the CI/CD team with 8 CPU and 16Gi
7. Generate the cluster report with all credentials at the end
Ask me for any choices you need to make along the way.
```

---

### Validating a config before using it

```
Validate this cluster config before I run plan_cluster:
[paste config YAML]
```

```
Check if my config has any CIDR conflicts or missing fields.
I don't want to start the cluster build until it's clean.
```

```
I'm not sure my pod_cidr is right for an OpenStack network on 10.x.x.x —
validate this config and tell me if there are any subnet conflicts.
```

---

### Managing multiple clusters

```
Save this cluster session as "prod" so I can switch back to it later.
```

```
Show me all the clusters I have saved and which one is active right now.
```

```
Switch to the "staging" cluster.
Then show me its status.
```

```
I need to work on three clusters today: prod, staging, and dev.
Save the current session as "prod", then help me create configs
for staging (same setup, different IPs) and dev (single-node).
```

---

### Reviewing the audit trail

```
Show me the last 20 actions taken on this cluster.
```

```
What did we do to the prod cluster in the last session?
Filter the audit log to show only prod cluster entries.
```

```
Show me all the times install_stack was called, on any cluster,
to see if there were any failures we need to follow up on.
```

---

### Using the examples directory

```
I'm new to this and want to start with a single-node dev cluster.
Use the single-node-dev.yaml example as a starting point.
What IPs do I need to change?
```

```
Show me the difference between the 3-node-production and 5-node-ha
example configs — when would I choose one over the other?
```

```
I have an OpenStack environment similar to the one in the examples.
Adapt the openstack-rhel-proxy.yaml example for my network:
proxy is at 10.50.0.1:3128, nodes are at 172.20.0.x
```

---

### When Claude needs more information

Claude will ask you for required information before calling a tool rather than guessing. For example:

```
You: Install monitoring
Claude: Which monitoring stack would you like?
        1. [prometheus] kube-prometheus-stack — Prometheus, Grafana, Alertmanager
        2. [prometheus-loki] Above + Loki for log aggregation + Promtail
        3. [none] Skip monitoring for now
        Also, what password would you like to set for Grafana? (default: admin-changeme)
```

```
You: Run a security audit
Claude: Which compliance standards should I check?
        1. [cis] CIS Kubernetes Benchmark (9 checks)
        2. [nsa-cisa] NSA/CISA Kubernetes Hardening Guide (5 checks)
        3. [pci-dss] PCI-DSS (4 checks)
        4. [soc2-iso27001] SOC2 / ISO27001 (5 checks)
        5. [all] Run all four standards (23 checks total)
```

After every tool call, Claude presents a numbered menu of contextual next steps. You can reply with a number, a description, or a completely new request.

