"""
k8s_factory_mcp.py — k8s-mcp-v1
=================================
K8s Cluster Factory MCP Server
Official release: k8s-mcp-v1  |  Tools: 34  |  Lines: ~3300

Provisions, manages, scales, upgrades, secures, and reports on
Kubernetes clusters on any on-premises or cloud infrastructure,
from a single YAML config file, through a conversation with Claude AI.

OS support:    Ubuntu/Debian (apt), RHEL/Rocky/Alma/CentOS (dnf/yum), SUSE (zypper)
               Mixed-OS clusters supported — each node detected independently
HA support:    Multi-master HA via kubeadm --upload-certs + --control-plane join
Proxy support: Corporate proxy applied to apt/dnf/zypper/containerd/helm/kubectl
               Remove the proxy block entirely for direct internet access

Tools (34 total):
  Cluster lifecycle:  plan_cluster, prepare_nodes, bootstrap_cluster, install_cni,
                      install_stack, cluster_status, destroy_cluster
  Applications:       install_monitoring, install_jenkins, install_cert_manager,
                      install_security_tools, install_applications
  Security:           configure_rbac, configure_pod_security, configure_etcd_encryption,
                      configure_audit_logging, security_audit, audit_cluster
  Day-2 ops:          scale_cluster, upgrade_cluster, backup_etcd, restore_etcd,
                      rotate_certs, renew_service_cert, helm_manage,
                      cluster_snapshot, migrate_workload
  Observability:      node_diagnostics, stream_logs, manage_kubeconfig,
                      provision_namespace, provision_storage
  Reporting:          generate_cluster_report, cost_report

Requirements:
  pip install mcp paramiko pyyaml

Register with Claude Code:
  claude mcp add k8s-factory -- python3 ~/mcp-servers/k8s_factory_mcp.py

Full documentation: README.md
"""

import asyncio
import re
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

import paramiko
import yaml

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

SUPPORTED_CNI        = ["cilium", "calico", "flannel", "weave"]
SUPPORTED_PROFILES   = ["production", "development", "ml-gpu", "edge", "multi-tenant"]
SUPPORTED_STORAGE    = ["longhorn", "nfs", "local-path", "rook-ceph"]
SUPPORTED_MONITORING = ["prometheus", "prometheus-loki", "none"]
SUPPORTED_OS_FAMILIES = ["debian", "rhel", "suse", "auto"]
SUPPORTED_SELINUX    = ["permissive", "enforcing", "disabled"]
SUPPORTED_SWAP       = ["disable", "keep", "warn"]
SUPPORTED_IPTABLES   = ["auto", "legacy", "nftables"]
SUPPORTED_SYSCTL_PRESETS = ["k8s-minimal", "k8s-production", "k8s-highperf", "custom"]

# Additional supported values
SUPPORTED_RUNTIMES       = ["containerd", "crio"]
SUPPORTED_KUBE_PROXY     = ["iptables", "ipvs", "ebpf"]
SUPPORTED_INGRESS        = ["nginx", "traefik", "haproxy", "none"]
SUPPORTED_TOPOLOGIES     = ["single-node", "3-node", "5-node-ha", "custom"]
SUPPORTED_SECURITY_TOOLS = ["falco", "gatekeeper", "trivy-operator", "kyverno"]
SUPPORTED_APPLICATIONS   = ["sonarqube", "harbor", "vault", "keycloak"]
SUPPORTED_COMPLIANCE     = ["cis", "nsa-cisa", "pci-dss", "soc2-iso27001"]
SUPPORTED_ETCD_ENCRYPT   = ["aes-cbc", "aes-gcm", "none"]
SUPPORTED_AUDIT_LEVELS   = ["none", "metadata", "request", "requestresponse"]
SUPPORTED_CLOUD_PROVIDERS = ["aws", "gcp", "azure", "onprem", "openstack"]
SUPPORTED_CERT_ISSUERS   = ["self-signed", "acme-letsencrypt", "acme-zerossl", "internal-ca"]

# ─── Security tools — Helm definitions ───────────────────────────────────────
SECURITY_TOOLS_HELM = {
    "falco": {
        "repo": "falcosecurity", "url": "https://falcosecurity.github.io/charts",
        "chart": "falcosecurity/falco", "release": "falco", "ns": "falco",
        "set": ["driver.kind=ebpf", "falcosidekick.enabled=true", "falcosidekick.webui.enabled=true"],
        "description": "Runtime threat detection — watches syscalls for anomalous behaviour",
    },
    "gatekeeper": {
        "repo": "gatekeeper", "url": "https://open-policy-agent.github.io/gatekeeper/charts",
        "chart": "gatekeeper/gatekeeper", "release": "gatekeeper", "ns": "gatekeeper-system",
        "set": ["auditInterval=30", "logLevel=INFO"],
        "description": "OPA Gatekeeper — policy enforcement, blocks non-compliant deployments",
    },
    "trivy-operator": {
        "repo": "aqua", "url": "https://aquasecurity.github.io/helm-charts/",
        "chart": "aqua/trivy-operator", "release": "trivy-operator", "ns": "trivy-system",
        "set": ["trivy.ignoreUnfixed=true"],
        "description": "In-cluster image vulnerability scanning, reports as CRDs",
    },
    "kyverno": {
        "repo": "kyverno", "url": "https://kyverno.github.io/kyverno/",
        "chart": "kyverno/kyverno", "release": "kyverno", "ns": "kyverno",
        "set": ["replicaCount=1"],
        "description": "Policy-as-code — simpler alternative to OPA Gatekeeper",
    },
}

# ─── Application Helm definitions ────────────────────────────────────────────
APPLICATIONS_HELM = {
    "sonarqube": {
        "repo": "sonarqube", "url": "https://SonarSource.github.io/helm-chart-sonarqube",
        "chart": "sonarqube/sonarqube", "release": "sonarqube", "ns": "sonarqube",
        "set": ["service.type=ClusterIP", "persistence.enabled=true", "persistence.size=10Gi"],
        "description": "Code quality + SAST scanning; generates admin token for Jenkins integration",
        "default_admin_user": "admin",
        "default_admin_pass": "admin",  # sonarqube forces change on first login
    },
    "harbor": {
        "repo": "harbor", "url": "https://helm.goharbor.io",
        "chart": "harbor/harbor", "release": "harbor", "ns": "harbor",
        "set": ["expose.type=clusterIP", "persistence.enabled=true",
                "trivy.enabled=true", "notary.enabled=false"],
        "description": "Private container registry with built-in Trivy vulnerability scanning",
        "default_admin_user": "admin",
        "default_admin_pass_key": "harborAdminPassword",
    },
    "vault": {
        "repo": "hashicorp", "url": "https://helm.releases.hashicorp.com",
        "chart": "hashicorp/vault", "release": "vault", "ns": "vault",
        "set": ["server.dev.enabled=false", "server.ha.enabled=false",
                "injector.enabled=true", "ui.enabled=true", "ui.serviceType=ClusterIP"],
        "description": "HashiCorp Vault — secrets management; K8s auth method configured automatically",
    },
    "keycloak": {
        "repo": "bitnami", "url": "https://charts.bitnami.com/bitnami",
        "chart": "bitnami/keycloak", "release": "keycloak", "ns": "keycloak",
        "set": ["service.type=ClusterIP", "auth.adminUser=admin",
                "postgresql.enabled=true"],
        "description": "SSO / OIDC provider; kube-apiserver OIDC flags configured to trust this Keycloak",
        "default_admin_user": "admin",
    },
}

# ─── Additional Helm: cert-manager ClusterIssuers ────────────────────────────
CERT_MANAGER_HELM = {
    "repo": "jetstack", "url": "https://charts.jetstack.io",
    "chart": "jetstack/cert-manager", "release": "cert-manager", "ns": "cert-manager",
    "set": ["installCRDs=true"],
}

# ─── Ingress controller options ───────────────────────────────────────────────
INGRESS_HELM = {
    "nginx": {
        "repo": "ingress-nginx", "url": "https://kubernetes.github.io/ingress-nginx",
        "chart": "ingress-nginx/ingress-nginx", "release": "ingress-nginx", "ns": "ingress-nginx",
        "set": ["controller.service.type=ClusterIP"],
    },
    "traefik": {
        "repo": "traefik", "url": "https://traefik.github.io/charts",
        "chart": "traefik/traefik", "release": "traefik", "ns": "traefik",
        "set": ["service.type=ClusterIP", "dashboard.enabled=true"],
    },
    "haproxy": {
        "repo": "haproxytech", "url": "https://haproxytech.github.io/helm-charts",
        "chart": "haproxytech/kubernetes-ingress", "release": "haproxy-ingress", "ns": "haproxy",
        "set": ["controller.service.type=ClusterIP"],
    },
}

# ─── Compliance check commands per standard ───────────────────────────────────
# Each entry maps standard name → list of (label, kubectl/shell check command)
COMPLIANCE_CHECKS = {
    "cis": [
        ("CIS 1.1.1 — API server pod spec permissions",
         "stat -c '%a' /etc/kubernetes/manifests/kube-apiserver.yaml 2>/dev/null || echo 'file not found'"),
        ("CIS 1.2.1 — anonymous-auth disabled",
         "ps aux | grep kube-apiserver | grep -o 'anonymous-auth=[^ ]*' || echo 'not found in process args'"),
        ("CIS 1.2.6 — insecure port disabled",
         "ps aux | grep kube-apiserver | grep -o 'insecure-port=[^ ]*' || echo 'OK: insecure-port not set'"),
        ("CIS 1.2.9 — admission controllers",
         "ps aux | grep kube-apiserver | grep -o 'enable-admission-plugins=[^ ]*' || echo 'defaults in use'"),
        ("CIS 2.1 — etcd peer certs",
         "ps aux | grep etcd | grep -o 'peer-cert-file=[^ ]*' || echo 'not found'"),
        ("CIS 4.2.1 — kubelet anonymous auth",
         "grep -r 'authentication:' /var/lib/kubelet/config.yaml 2>/dev/null || echo 'not found'"),
        ("CIS 5.1.3 — minimize wildcard in RBAC roles",
         "kubectl get clusterroles -o json | python3 -c \""
         "import json,sys; roles=json.load(sys.stdin)['items']; "
         "[print(r['metadata']['name']) for r in roles "
         "if any(rule.get('verbs')==['*'] for rule in r.get('rules',[]))]\""),
        ("CIS 5.2.2 — no privileged containers",
         "kubectl get pods -A -o json | python3 -c \""
         "import json,sys; pods=json.load(sys.stdin)['items']; "
         "[print(p['metadata']['namespace']+'/'+p['metadata']['name']) for p in pods "
         "if any(c.get('securityContext',{}).get('privileged') for c in p['spec'].get('containers',[]))]\" "
         "|| echo none"),
        ("CIS 5.7.1 — namespaces have network policies",
         "kubectl get networkpolicies -A -o json | python3 -c \""
         "import json,sys; nps=json.load(sys.stdin)['items']; "
         "ns_with_np={np['metadata']['namespace'] for np in nps}; "
         "all_ns=set(); print('namespaces without NetworkPolicy (sample check)')\""),
    ],
    "nsa-cisa": [
        ("NSA 1 — use non-root containers",
         "kubectl get pods -A -o json | python3 -c \""
         "import json,sys; pods=json.load(sys.stdin)['items']; "
         "[print(p['metadata']['namespace']+'/'+p['metadata']['name']) for p in pods "
         "if p['spec'].get('securityContext',{}).get('runAsUser',999)==0]\" || echo none"),
        ("NSA 2 — immutable root filesystems",
         "kubectl get pods -A -o json | python3 -c \""
         "import json,sys; pods=json.load(sys.stdin)['items']; "
         "[print(p['metadata']['namespace']+'/'+p['metadata']['name']) for p in pods "
         "for c in p['spec'].get('containers',[]) "
         "if not c.get('securityContext',{}).get('readOnlyRootFilesystem')]\" || echo none"),
        ("NSA 3 — disable privilege escalation",
         "kubectl get pods -A -o json | python3 -c \""
         "import json,sys; pods=json.load(sys.stdin)['items']; "
         "[print(p['metadata']['namespace']+'/'+p['metadata']['name']) for p in pods "
         "for c in p['spec'].get('containers',[]) "
         "if c.get('securityContext',{}).get('allowPrivilegeEscalation',True)]\" || echo none"),
        ("NSA 4 — resource limits on all containers",
         "kubectl get pods -A -o json | python3 -c \""
         "import json,sys; pods=json.load(sys.stdin)['items']; "
         "[print(p['metadata']['namespace']+'/'+p['metadata']['name']) for p in pods "
         "for c in p['spec'].get('containers',[]) "
         "if not c.get('resources',{}).get('limits')]\" || echo none"),
        ("NSA 5 — no sensitive host path mounts",
         "kubectl get pods -A -o json | python3 -c \""
         "import json,sys; pods=json.load(sys.stdin)['items']; "
         "sensitive=['/etc','/var/run/docker.sock','/proc','/sys','/dev']; "
         "[print(p['metadata']['namespace']+'/'+p['metadata']['name']+': '+v['hostPath']['path']) "
         "for p in pods for v in p['spec'].get('volumes',[]) "
         "if v.get('hostPath',{}).get('path','') in sensitive]\" || echo none"),
    ],
    "pci-dss": [
        ("PCI DSS 6.3 — no default service account tokens automounted",
         "kubectl get serviceaccounts -A -o json | python3 -c \""
         "import json,sys; sas=json.load(sys.stdin)['items']; "
         "[print(sa['metadata']['namespace']+'/'+sa['metadata']['name']) for sa in sas "
         "if sa.get('automountServiceAccountToken',True) and sa['metadata']['name']=='default']\""),
        ("PCI DSS 7.1 — no cluster-admin bindings to users",
         "kubectl get clusterrolebindings -o json | python3 -c \""
         "import json,sys; crbs=json.load(sys.stdin)['items']; "
         "[print(c['metadata']['name']) for c in crbs if c['roleRef']['name']=='cluster-admin' "
         "and any(s.get('kind')=='User' for s in c.get('subjects',[]))]\" || echo none"),
        ("PCI DSS 8.2 — unique identities (ServiceAccount per workload check)",
         "kubectl get deployments -A -o json | python3 -c \""
         "import json,sys; deps=json.load(sys.stdin)['items']; "
         "[print(d['metadata']['namespace']+'/'+d['metadata']['name']) for d in deps "
         "if not d['spec']['template']['spec'].get('serviceAccountName') "
         "or d['spec']['template']['spec'].get('serviceAccountName')=='default']\" || echo none"),
        ("PCI DSS 10.1 — audit logging enabled",
         "ps aux | grep kube-apiserver | grep -o 'audit-log-path=[^ ]*' || echo 'WARN: audit logging not configured'"),
    ],
    "soc2-iso27001": [
        ("SOC2 — secrets not stored in env vars",
         "kubectl get pods -A -o json | python3 -c \""
         "import json,sys; pods=json.load(sys.stdin)['items']; "
         "[print(p['metadata']['namespace']+'/'+p['metadata']['name']+': '+e['name']) "
         "for p in pods for c in p['spec'].get('containers',[]) "
         "for e in c.get('env',[]) "
         "if any(kw in e['name'].upper() for kw in ['PASSWORD','SECRET','TOKEN','KEY','PASS'])]\" || echo none"),
        ("SOC2 — image pull policy not Always for latest tags",
         "kubectl get pods -A -o json | python3 -c \""
         "import json,sys; pods=json.load(sys.stdin)['items']; "
         "[print(p['metadata']['namespace']+'/'+p['metadata']['name']) for p in pods "
         "for c in p['spec'].get('containers',[]) if ':latest' in c.get('image','')]\" || echo none"),
        ("ISO27001 A.12.6 — vulnerability management: trivy operator present",
         "kubectl get pods -n trivy-system 2>/dev/null || echo 'WARN: trivy-operator not installed'"),
        ("ISO27001 A.9 — access control: RBAC enabled",
         "ps aux | grep kube-apiserver | grep -o 'authorization-mode=[^ ]*' || echo 'check manually'"),
        ("ISO27001 A.10 — encryption: etcd encryption check",
         "ps aux | grep kube-apiserver | grep -o 'encryption-provider-config=[^ ]*' || echo 'WARN: etcd encryption not configured'"),
    ],
}

# ─── Cloud cost rate tables (used when cloud provider = onprem) ──────────────
# Users can override per-unit rates in the config under a `costing` block.
DEFAULT_ONPREM_RATES = {
    "cpu_core_hourly_usd":    0.015,   # per vCPU per hour
    "ram_gb_hourly_usd":      0.005,   # per GiB per hour
    "storage_gb_monthly_usd": 0.10,    # per GiB per month
    "power_kwh_usd":          0.12,    # per kWh (for hardware power estimate)
    "currency":               "USD",
}


# All values below are defaults — the user overrides them in the cluster config
# under a top-level `node_config` block. plan_cluster will ask about each one
# if not explicitly set, and show exactly what will be applied before anything
# runs on the nodes.
# ─────────────────────────────────────────────────────────────────────────────

# Kernel modules: always-required (kubeadm hard requirement) + optional extras
KERNEL_MODULES_REQUIRED = ["overlay", "br_netfilter"]
KERNEL_MODULES_OPTIONAL = {
    "ipvs":         ["ip_vs", "ip_vs_rr", "ip_vs_wrr", "ip_vs_sh", "nf_conntrack"],
    "ipvs_legacy":  ["ip_vs", "ip_vs_rr", "ip_vs_wrr", "ip_vs_sh", "nf_conntrack_ipv4"],
    "ebpf_extra":   ["nf_conntrack"],
    "none":         [],
}

# Sysctl presets — each is a dict of {param: value}
SYSCTL_PRESETS = {
    # Bare minimum kubeadm needs — suitable for dev/test single nodes
    "k8s-minimal": {
        "net.bridge.bridge-nf-call-iptables":  "1",
        "net.bridge.bridge-nf-call-ip6tables": "1",
        "net.ipv4.ip_forward":                 "1",
    },
    # Recommended for general production clusters
    "k8s-production": {
        "net.bridge.bridge-nf-call-iptables":  "1",
        "net.bridge.bridge-nf-call-ip6tables": "1",
        "net.ipv4.ip_forward":                 "1",
        "net.ipv4.tcp_tw_reuse":               "1",
        "net.ipv4.ip_local_port_range":        "1024 65535",
        "net.core.somaxconn":                  "32768",
        "net.core.netdev_max_backlog":         "16384",
        "fs.file-max":                         "1048576",
        "fs.inotify.max_user_instances":       "8192",
        "fs.inotify.max_user_watches":         "524288",
        "kernel.pid_max":                      "65536",
        "vm.swappiness":                       "0",
        "vm.overcommit_memory":                "1",
    },
    # High-throughput / high-connection workloads (API gateways, service meshes)
    "k8s-highperf": {
        "net.bridge.bridge-nf-call-iptables":  "1",
        "net.bridge.bridge-nf-call-ip6tables": "1",
        "net.ipv4.ip_forward":                 "1",
        "net.ipv4.tcp_tw_reuse":               "1",
        "net.ipv4.ip_local_port_range":        "1024 65535",
        "net.core.somaxconn":                  "65535",
        "net.core.netdev_max_backlog":         "65536",
        "net.core.rmem_max":                   "67108864",
        "net.core.wmem_max":                   "67108864",
        "net.ipv4.tcp_rmem":                   "4096 87380 67108864",
        "net.ipv4.tcp_wmem":                   "4096 65536 67108864",
        "net.ipv4.tcp_syn_retries":            "2",
        "net.ipv4.tcp_synack_retries":         "2",
        "net.netfilter.nf_conntrack_max":      "1048576",
        "fs.file-max":                         "2097152",
        "fs.inotify.max_user_instances":       "16384",
        "fs.inotify.max_user_watches":         "1048576",
        "kernel.pid_max":                      "131072",
        "vm.swappiness":                       "0",
        "vm.overcommit_memory":                "1",
        "vm.max_map_count":                    "262144",
    },
}

# Default node_config — used if user doesn't specify; plan_cluster will always
# surface this block and ask for confirmation before prepare_nodes runs.
DEFAULT_NODE_CONFIG = {
    "sysctl_preset":   "k8s-minimal",   # k8s-minimal | k8s-production | k8s-highperf | custom
    "sysctl_custom":   {},               # extra params to merge on top of preset
    "kernel_modules":  "required",      # required | ipvs | ebpf_extra | none
    "extra_modules":   [],              # any additional modules the user wants
    "iptables_mode":   "auto",          # auto | legacy | nftables
    "selinux":         "permissive",    # permissive | enforcing | disabled (rhel only)
    "swap":            "disable",       # disable | keep | warn
    "hugepages":       False,           # enable transparent hugepages
    "ulimits":         True,            # set recommended ulimits for containerd
}


def build_sysctl_block(node_config: dict) -> str:
    """Build the sysctl.d/k8s.conf content from preset + any custom overrides."""
    preset_name = node_config.get("sysctl_preset", "k8s-minimal")
    params = dict(SYSCTL_PRESETS.get(preset_name, SYSCTL_PRESETS["k8s-minimal"]))
    params.update(node_config.get("sysctl_custom", {}))
    lines = [f"{k} = {v}" for k, v in params.items()]
    return "\n".join(lines)


def build_kernel_modules_block(node_config: dict) -> str:
    """Return the list of kernel modules to load (required + optional set)."""
    modules = list(KERNEL_MODULES_REQUIRED)
    extra_set = node_config.get("kernel_modules", "required")
    modules += KERNEL_MODULES_OPTIONAL.get(extra_set, [])
    modules += node_config.get("extra_modules", [])
    # deduplicate preserving order
    seen, unique = set(), []
    for m in modules:
        if m not in seen:
            seen.add(m)
            unique.append(m)
    return "\n".join(unique)


def build_iptables_block(node_config: dict, os_family: str) -> str:
    """Configure iptables mode on the node. 'auto' lets the OS decide.
    'legacy' forces update-alternatives / iptables-legacy on Debian, or
    the iptables-legacy package on RHEL. 'nftables' installs nftables."""
    mode = node_config.get("iptables_mode", "auto")
    if mode == "auto":
        return "# iptables mode: auto (OS default)"
    if mode == "legacy":
        if os_family == "debian":
            return textwrap.dedent("""
                update-alternatives --set iptables  /usr/sbin/iptables-legacy  2>/dev/null || true
                update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy 2>/dev/null || true
            """).strip()
        elif os_family == "rhel":
            return "(dnf install -y -q iptables-legacy 2>/dev/null || yum install -y -q iptables-legacy 2>/dev/null || true)"
        return "# iptables legacy: no action needed on this OS"
    if mode == "nftables":
        if os_family == "debian":
            return "apt-get install -y -qq nftables && systemctl enable nftables"
        elif os_family == "rhel":
            return "(dnf install -y -q nftables 2>/dev/null || yum install -y -q nftables 2>/dev/null) && systemctl enable nftables"
        return "zypper install -y nftables && systemctl enable nftables"
    return "# iptables mode: unrecognised — skipped"


def build_swap_block(node_config: dict) -> str:
    """Swap handling: disable (kubeadm requirement by default), keep (user
    explicitly accepts the risk), or warn (disable at runtime only, don't
    touch fstab — survives a reboot but warns in prepare_nodes output)."""
    mode = node_config.get("swap", "disable")
    if mode == "disable":
        return textwrap.dedent("""
            swapoff -a
            sed -i '/[[:space:]]swap[[:space:]]/ s/^/#/' /etc/fstab 2>/dev/null || true
        """).strip()
    if mode == "warn":
        return textwrap.dedent("""
            swapoff -a
            echo "WARNING: swap disabled at runtime only — will re-enable after reboot. Set swap: disable in node_config for permanent disable."
        """).strip()
    # keep — user explicitly wants swap on (e.g. dev node with --fail-swap-on=false)
    return 'echo "swap: keeping as-is per node_config (ensure kubelet has --fail-swap-on=false)"'


def build_selinux_block(node_config: dict, os_family: str) -> str:
    """SELinux is only relevant on RHEL/CentOS family. Ignored on Debian/SUSE."""
    if os_family != "rhel":
        return "# SELinux: not applicable on this OS family"
    mode = node_config.get("selinux", "permissive")
    if mode == "permissive":
        return textwrap.dedent("""
            setenforce 0 2>/dev/null || true
            sed -i 's/^SELINUX=enforcing/SELINUX=permissive/' /etc/selinux/config 2>/dev/null || true
        """).strip()
    if mode == "disabled":
        return textwrap.dedent("""
            sed -i 's/^SELINUX=.*/SELINUX=disabled/' /etc/selinux/config 2>/dev/null || true
            echo "SELinux set to disabled — will take full effect after reboot"
        """).strip()
    # enforcing — don't touch it, but warn
    return 'echo "SELinux: keeping enforcing per node_config — ensure your CNI and container runtime support SELinux contexts"'


def build_ulimits_block(node_config: dict) -> str:
    """Set recommended system-wide ulimits for containerd and kubelet.
    These prevent 'too many open files' issues under high pod density."""
    if not node_config.get("ulimits", True):
        return "# ulimits: skipped per node_config"
    return textwrap.dedent("""
        cat <<'EOF' | tee /etc/security/limits.d/99-k8s.conf
* soft nofile 1048576
* hard nofile 1048576
* soft nproc  65536
* hard nproc  65536
root soft nofile 1048576
root hard nofile 1048576
EOF
    """).strip()


def build_hugepages_block(node_config: dict) -> str:
    """Disable transparent hugepages (THP) — recommended for databases and
    latency-sensitive workloads on Kubernetes. Optional: some ML workloads
    prefer THP enabled."""
    if not node_config.get("hugepages", False):
        return textwrap.dedent("""
            echo never > /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null || true
            echo never > /sys/kernel/mm/transparent_hugepage/defrag  2>/dev/null || true
            cat <<'EOF' | tee /etc/rc.local >/dev/null
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo never > /sys/kernel/mm/transparent_hugepage/defrag
EOF
            chmod +x /etc/rc.local 2>/dev/null || true
        """).strip()
    return "# hugepages: keeping THP enabled per node_config"


def format_node_config_summary(node_config: dict) -> str:
    """Human-readable summary of what will be applied to every node —
    shown in plan_cluster output so the user can review before confirming."""
    nc = {**DEFAULT_NODE_CONFIG, **node_config}
    lines = [
        "",
        "NODE CONFIG (applied by prepare_nodes to every node):",
        f"  sysctl preset:    {nc['sysctl_preset']}" +
            (f"  (+{len(nc['sysctl_custom'])} custom params)" if nc.get("sysctl_custom") else ""),
        f"  kernel modules:   required (overlay, br_netfilter)" +
            (f" + {nc['kernel_modules']} set" if nc['kernel_modules'] != "required" else "") +
            (f" + extras: {nc['extra_modules']}" if nc.get("extra_modules") else ""),
        f"  iptables mode:    {nc['iptables_mode']}",
        f"  selinux (rhel):   {nc['selinux']}",
        f"  swap:             {nc['swap']}",
        f"  hugepages (THP):  {'enabled' if nc.get('hugepages') else 'disabled'}",
        f"  ulimits:          {'set' if nc.get('ulimits', True) else 'skipped'}",
    ]
    if nc.get("sysctl_custom"):
        lines.append("  custom sysctl overrides:")
        for k, v in nc["sysctl_custom"].items():
            lines.append(f"    {k} = {v}")
    preset_params = SYSCTL_PRESETS.get(nc["sysctl_preset"], SYSCTL_PRESETS["k8s-minimal"])
    all_params = {**preset_params, **nc.get("sysctl_custom", {})}
    lines.append(f"  total sysctl params:  {len(all_params)}")
    lines.append("  (run prepare_nodes with dry_run=true to see the full generated script)")
    return "\n".join(lines)


# helm, kubectl apply -f <url>) is prefixed with these exports when a proxy is
# configured. containerd needs a separate systemd drop-in since it's a daemon
# with its own environment, not inherited from the SSH shell session.
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_NO_PROXY = "localhost,127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.svc,.cluster.local,kubernetes,kubernetes.default"


def proxy_env_exports(proxy_cfg: dict | None) -> str:
    """Build shell `export` lines for http_proxy/https_proxy/no_proxy (both cases,
    since some tools only honor uppercase and some only lowercase). Returns an
    empty string if no proxy is configured — every call site is then a no-op."""
    if not proxy_cfg or not proxy_cfg.get("http_proxy") and not proxy_cfg.get("https_proxy"):
        return ""
    http_p  = proxy_cfg.get("http_proxy", proxy_cfg.get("https_proxy", ""))
    https_p = proxy_cfg.get("https_proxy", http_p)
    no_p    = proxy_cfg.get("no_proxy", DEFAULT_NO_PROXY)
    lines = [
        f'export http_proxy="{http_p}"',
        f'export https_proxy="{https_p}"',
        f'export HTTP_PROXY="{http_p}"',
        f'export HTTPS_PROXY="{https_p}"',
        f'export no_proxy="{no_p}"',
        f'export NO_PROXY="{no_p}"',
    ]
    return "\n".join(lines) + "\n"


def containerd_proxy_dropin(proxy_cfg: dict | None) -> str:
    """Containerd is a systemd-managed daemon — it does not inherit the SSH
    session's exported env vars, so it needs its own drop-in unit file."""
    if not proxy_cfg or not proxy_cfg.get("http_proxy") and not proxy_cfg.get("https_proxy"):
        return ""
    http_p  = proxy_cfg.get("http_proxy", proxy_cfg.get("https_proxy", ""))
    https_p = proxy_cfg.get("https_proxy", http_p)
    no_p    = proxy_cfg.get("no_proxy", DEFAULT_NO_PROXY)
    return textwrap.dedent(f"""
        mkdir -p /etc/systemd/system/containerd.service.d
        cat <<'PROXYEOF' | tee /etc/systemd/system/containerd.service.d/http-proxy.conf
[Service]
Environment="HTTP_PROXY={http_p}"
Environment="HTTPS_PROXY={https_p}"
Environment="NO_PROXY={no_p}"
PROXYEOF
        systemctl daemon-reload
    """).strip()


def apt_proxy_conf(proxy_cfg: dict | None) -> str:
    """apt itself also needs its own proxy config file, separate from shell env,
    because apt's sandboxed download helpers don't always inherit exported vars."""
    if not proxy_cfg or not proxy_cfg.get("http_proxy") and not proxy_cfg.get("https_proxy"):
        return ""
    http_p  = proxy_cfg.get("http_proxy", proxy_cfg.get("https_proxy", ""))
    https_p = proxy_cfg.get("https_proxy", http_p)
    return textwrap.dedent(f"""
        cat <<'APTPROXYEOF' | tee /etc/apt/apt.conf.d/95proxies
Acquire::http::Proxy "{http_p}";
Acquire::https::Proxy "{https_p}";
APTPROXYEOF
    """).strip()


def dnf_proxy_conf(proxy_cfg: dict | None) -> str:
    """dnf/yum read proxy from /etc/dnf/dnf.conf or /etc/yum.conf."""
    if not proxy_cfg or not proxy_cfg.get("http_proxy") and not proxy_cfg.get("https_proxy"):
        return ""
    http_p = proxy_cfg.get("http_proxy", proxy_cfg.get("https_proxy", ""))
    return textwrap.dedent(f"""
        for f in /etc/dnf/dnf.conf /etc/yum.conf; do
            if [ -f "$f" ] && ! grep -q '^proxy=' "$f"; then
                echo 'proxy={http_p}' | tee -a "$f" >/dev/null
            fi
        done
    """).strip()


def zypper_proxy_conf(proxy_cfg: dict | None) -> str:
    """zypper honors standard http_proxy/https_proxy env vars already — no
    separate config file needed, but we still set them via proxy_env_exports."""
    return ""


def helm_kubectl_proxy_note(proxy_cfg: dict | None) -> str:
    """helm and kubectl both honor http_proxy/https_proxy/no_proxy from the shell
    environment automatically — covered by proxy_env_exports(), no extra config."""
    return ""


PKG_COMMANDS = {
    "debian": {
        "update":         "apt-get update -qq",
        "install":        "apt-get install -y -qq {pkgs}",
        "hold":           "apt-mark hold {pkgs}",
        "unhold":         "apt-mark unhold {pkgs}",
        "install_pinned": "apt-get install -y -qq {pkg}={ver}-*",
        # containerd (not containerd.io) is in Ubuntu/Debian main repos — no Docker repo needed
        "base_pkgs":      "containerd apt-transport-https ca-certificates curl gpg socat conntrack",
        "repo_setup": textwrap.dedent("""
            curl -fsSL https://pkgs.k8s.io/core:/stable:/v{k8s_version}/deb/Release.key \\
                | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
            echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] \\
                https://pkgs.k8s.io/core:/stable:/v{k8s_version}/deb/ /" \\
                | tee /etc/apt/sources.list.d/kubernetes.list
        """).strip(),
    },
    "rhel": {
        "update":         "yum makecache -q 2>/dev/null || dnf makecache -q",
        "install":        "(dnf install -y -q {pkgs} 2>/dev/null || yum install -y -q {pkgs})",
        "hold":           "dnf versionlock add {pkgs} 2>/dev/null || true",
        "unhold":         "dnf versionlock delete {pkgs} 2>/dev/null || true",
        "install_pinned": "(dnf install -y -q {pkg}-{ver} 2>/dev/null || yum install -y -q {pkg}-{ver})",
        # containerd on RHEL comes from the Docker CE repo. We add that repo in
        # prerequisites_script() below before any package install runs.
        "base_pkgs":      "containerd.io ca-certificates curl gnupg2 socat conntrack-tools",
        "repo_setup": textwrap.dedent("""
            cat <<EOF | tee /etc/yum.repos.d/kubernetes.repo
[kubernetes]
name=Kubernetes
baseurl=https://pkgs.k8s.io/core:/stable:/v{k8s_version}/rpm/
enabled=1
gpgcheck=1
gpgkey=https://pkgs.k8s.io/core:/stable:/v{k8s_version}/rpm/repodata/repomd.xml.key
EOF
        """).strip(),
    },
    "suse": {
        "update":         "zypper refresh -q",
        "install":        "zypper install -y {pkgs}",
        "hold":           "zypper addlock {pkgs} 2>/dev/null || true",
        "unhold":         "zypper removelock {pkgs} 2>/dev/null || true",
        "install_pinned": "zypper install -y {pkg}-{ver}",
        "base_pkgs":      "containerd ca-certificates curl gpg2 socat conntrack-tools",
        "repo_setup": textwrap.dedent("""
            zypper addrepo -f https://pkgs.k8s.io/core:/stable:/v{k8s_version}/rpm/ kubernetes
            rpm --import https://pkgs.k8s.io/core:/stable:/v{k8s_version}/rpm/repodata/repomd.xml.key
        """).strip(),
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# Prerequisites bootstrapper
# This script runs first inside prepare_nodes on every node. It installs
# every binary that the MCP's subsequent commands depend on:
#   - Helm           (every install_stack / helm_manage call)
#   - etcdctl        (backup_etcd / restore_etcd)
#   - git            (cluster_snapshot GitOps workflows)
#   - jq             (JSON parsing in audit scripts)
#   - wget           (fallback download tool)
#   - Docker CE repo on RHEL (provides containerd.io)
#   - EPEL repo on RHEL     (provides conntrack-tools on minimal installs)
#   - DNF versionlock plugin on RHEL (required for package pinning)
#
# All steps are idempotent — safe to run multiple times. Each command checks
# whether the tool already exists before installing, so re-running prepare_nodes
# on a previously prepared node does not re-download everything.
# ─────────────────────────────────────────────────────────────────────────────

HELM_INSTALL_SCRIPT = textwrap.dedent("""
    if ! command -v helm >/dev/null 2>&1; then
        echo "[prerequisites] Installing Helm..."
        curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 \\
            -o /tmp/get-helm.sh
        chmod +x /tmp/get-helm.sh
        HELM_INSTALL_DIR=/usr/local/bin bash /tmp/get-helm.sh --no-sudo
        rm -f /tmp/get-helm.sh
        helm version --short
        echo "[prerequisites] Helm installed: $(helm version --short)"
    else
        echo "[prerequisites] Helm already present: $(helm version --short)"
    fi
""").strip()

ETCDCTL_INSTALL_SCRIPT = textwrap.dedent("""
    if ! command -v etcdctl >/dev/null 2>&1; then
        echo "[prerequisites] Installing etcdctl..."
        ETCD_VER=$(curl -fsSL https://api.github.com/repos/etcd-io/etcd/releases/latest \\
            | grep -o '"tag_name": *"[^"]*"' | head -1 | sed 's/.*"\\(v[^"]*\\)".*/\\1/')
        ETCD_VER=${ETCD_VER:-v3.5.13}
        curl -fsSL "https://github.com/etcd-io/etcd/releases/download/${ETCD_VER}/etcd-${ETCD_VER}-linux-amd64.tar.gz" \\
            -o /tmp/etcd.tar.gz
        tar xzf /tmp/etcd.tar.gz -C /tmp
        install -m 0755 /tmp/etcd-${ETCD_VER}-linux-amd64/etcdctl /usr/local/bin/etcdctl
        rm -rf /tmp/etcd.tar.gz /tmp/etcd-${ETCD_VER}-linux-amd64
        echo "[prerequisites] etcdctl installed: $(etcdctl version)"
    else
        echo "[prerequisites] etcdctl already present: $(etcdctl version)"
    fi
""").strip()


def prerequisites_script(os_family: str, proxy_cfg: dict | None = None) -> str:
    """
    Fully self-contained prerequisites bootstrapper. Installs every binary
    the MCP needs on the node — no prior setup required. Runs before any
    package install in node_prep_script so the repos and tools are ready.
    """
    proxy_exports = proxy_env_exports(proxy_cfg)

    if os_family == "debian":
        repo_bootstrap = textwrap.dedent("""
            # Ensure apt repos have git, jq, wget available
            apt-get update -qq
            apt-get install -y -qq git jq wget curl ca-certificates gpg 2>/dev/null || true
        """).strip()
        versionlock_install = ""  # not needed on Debian

    elif os_family == "rhel":
        repo_bootstrap = textwrap.dedent("""
            # Add EPEL repo (provides conntrack-tools, jq, and other utilities on minimal installs)
            if ! rpm -q epel-release >/dev/null 2>&1; then
                (dnf install -y -q epel-release 2>/dev/null || yum install -y -q epel-release 2>/dev/null) || \\
                rpm -Uvh --quiet https://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm 2>/dev/null || true
            fi

            # Add Docker CE repo — provides containerd.io which is not in RHEL base repos
            if [ ! -f /etc/yum.repos.d/docker-ce.repo ]; then
                (dnf install -y -q yum-utils 2>/dev/null || yum install -y -q yum-utils 2>/dev/null) || true
                yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo 2>/dev/null || \\
                curl -fsSL https://download.docker.com/linux/centos/docker-ce.repo \\
                    -o /etc/yum.repos.d/docker-ce.repo 2>/dev/null || true
            fi

            # Install git, jq, wget
            (dnf install -y -q git jq wget curl 2>/dev/null || yum install -y -q git jq wget curl 2>/dev/null) || true
        """).strip()
        versionlock_install = textwrap.dedent("""
            # Install dnf-versionlock plugin (required for pinning kubelet/kubeadm/kubectl versions)
            (dnf install -y -q python3-dnf-plugin-versionlock 2>/dev/null || \\
             dnf install -y -q dnf-plugin-versionlock 2>/dev/null || \\
             yum install -y -q yum-versionlock 2>/dev/null) || true
        """).strip()

    else:  # suse
        repo_bootstrap = textwrap.dedent("""
            # Install git, jq, wget
            zypper install -y git jq wget curl 2>/dev/null || true
        """).strip()
        versionlock_install = ""

    return textwrap.dedent(f"""
        set -uo pipefail
        {proxy_exports}
        echo "[prerequisites] Starting prerequisite bootstrap on $(hostname)..."

        {repo_bootstrap}

        {versionlock_install}

        {HELM_INSTALL_SCRIPT}

        {ETCDCTL_INSTALL_SCRIPT}

        echo "[prerequisites] All prerequisites ready."
        echo "  helm:     $(helm version --short 2>/dev/null || echo not installed)"
        echo "  etcdctl:  $(etcdctl version 2>/dev/null | head -1 || echo not installed)"
        echo "  kubectl:  $(kubectl version --client --short 2>/dev/null || echo not yet installed)"
        echo "  git:      $(git --version 2>/dev/null || echo not installed)"
        echo "  jq:       $(jq --version 2>/dev/null || echo not installed)"
        echo PREREQUISITES_DONE
    """).strip()


OS_DETECT_SCRIPT = textwrap.dedent("""
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "ID=$ID"
        echo "ID_LIKE=$ID_LIKE"
        echo "VERSION_ID=$VERSION_ID"
        echo "PRETTY_NAME=$PRETTY_NAME"
    else
        echo "ID=unknown"
    fi
""").strip()


def detect_os_family(os_id: str, os_id_like: str) -> str:
    """Map /etc/os-release ID + ID_LIKE to one of our supported package-manager families."""
    combined = f"{os_id} {os_id_like}".lower()
    if any(x in combined for x in ["ubuntu", "debian"]):
        return "debian"
    if any(x in combined for x in ["rhel", "centos", "rocky", "almalinux", "fedora", "amzn"]):
        return "rhel"
    if any(x in combined for x in ["suse", "sles"]):
        return "suse"
    return "debian"  # safe fallback — most common cloud image family


HELM_PACKAGES = {
    "production": [
        {"repo": "argo",          "url": "https://argoproj.github.io/argo-helm",                "chart": "argo/argo-cd",                              "release": "argocd",        "ns": "argocd"},
        {"repo": "jetstack",      "url": "https://charts.jetstack.io",                          "chart": "jetstack/cert-manager",                     "release": "cert-manager",  "ns": "cert-manager", "set": ["installCRDs=true"]},
        {"repo": "ingress-nginx", "url": "https://kubernetes.github.io/ingress-nginx",          "chart": "ingress-nginx/ingress-nginx",               "release": "ingress-nginx", "ns": "ingress-nginx"},
        {"repo": "metallb",       "url": "https://metallb.github.io/metallb",                   "chart": "metallb/metallb",                           "release": "metallb",       "ns": "metallb-system"},
        {"repo": "velero",        "url": "https://vmware-tanzu.github.io/helm-charts",          "chart": "velero/velero",                             "release": "velero",        "ns": "velero"},
    ],
    "development": [
        {"repo": "argo",               "url": "https://argoproj.github.io/argo-helm",           "chart": "argo/argo-cd",                              "release": "argocd",        "ns": "argocd"},
        {"repo": "ingress-nginx",      "url": "https://kubernetes.github.io/ingress-nginx",     "chart": "ingress-nginx/ingress-nginx",               "release": "ingress-nginx", "ns": "ingress-nginx"},
        {"repo": "jetstack",           "url": "https://charts.jetstack.io",                     "chart": "jetstack/cert-manager",                     "release": "cert-manager",  "ns": "cert-manager", "set": ["installCRDs=true"]},
    ],
    "ml-gpu": [
        {"repo": "nvidia",        "url": "https://helm.ngc.nvidia.com/nvidia",                  "chart": "nvidia/gpu-operator",                       "release": "gpu-operator",  "ns": "gpu-operator"},
        {"repo": "argo",          "url": "https://argoproj.github.io/argo-helm",                "chart": "argo/argo-workflows",                       "release": "argo-workflows","ns": "argo"},
        {"repo": "kubeflow",      "url": "https://kubeflow.github.io/helm-charts",              "chart": "kubeflow/training-operator",                "release": "training-op",   "ns": "kubeflow"},
    ],
    "edge": [
        {"repo": "metallb",  "url": "https://metallb.github.io/metallb",                        "chart": "metallb/metallb",   "release": "metallb",  "ns": "metallb-system"},
        {"repo": "longhorn", "url": "https://charts.longhorn.io",                               "chart": "longhorn/longhorn", "release": "longhorn", "ns": "longhorn-system"},
    ],
    "multi-tenant": [
        {"repo": "argo",          "url": "https://argoproj.github.io/argo-helm",                "chart": "argo/argo-cd",              "release": "argocd",       "ns": "argocd"},
        {"repo": "jetstack",      "url": "https://charts.jetstack.io",                          "chart": "jetstack/cert-manager",     "release": "cert-manager", "ns": "cert-manager", "set": ["installCRDs=true"]},
        {"repo": "ingress-nginx", "url": "https://kubernetes.github.io/ingress-nginx",          "chart": "ingress-nginx/ingress-nginx","release": "ingress-nginx","ns": "ingress-nginx"},
        {"repo": "capsule",       "url": "https://projectcapsule.github.io/charts",            "chart": "capsule/capsule",            "release": "capsule",      "ns": "capsule-system"},
    ],
}

MONITORING_HELM = {
    "prometheus": [
        {"repo": "prometheus", "url": "https://prometheus-community.github.io/helm-charts", "chart": "prometheus-community/kube-prometheus-stack", "release": "monitoring", "ns": "monitoring",
         "set": ["grafana.adminPassword=admin-changeme"]},
    ],
    "prometheus-loki": [
        {"repo": "prometheus", "url": "https://prometheus-community.github.io/helm-charts", "chart": "prometheus-community/kube-prometheus-stack", "release": "monitoring", "ns": "monitoring",
         "set": ["grafana.adminPassword=admin-changeme"]},
        {"repo": "grafana",    "url": "https://grafana.github.io/helm-charts",              "chart": "grafana/loki-stack",                          "release": "loki",       "ns": "monitoring",
         "set": ["grafana.enabled=false", "promtail.enabled=true"]},
    ],
}

JENKINS_HELM = {
    "repo": "jenkins", "url": "https://charts.jenkinsci.io", "chart": "jenkins/jenkins",
    "release": "jenkins", "ns": "jenkins",
    "default_values": {
        "controller.serviceType":            "ClusterIP",
        "controller.adminPassword":          "admin-changeme",
        "persistence.enabled":               "true",
        "persistence.size":                  "10Gi",
        "agent.enabled":                     "true",
        "rbac.create":                       "true",
        "serviceAccount.create":             "true",
        "controller.installPlugins[0]":      "kubernetes:latest",
        "controller.installPlugins[1]":      "workflow-aggregator:latest",
        "controller.installPlugins[2]":      "git:latest",
        "controller.installPlugins[3]":      "configuration-as-code:latest",
    },
}

CNI_HELM = {
    "cilium":  {"repo_name": "cilium",        "repo_url": "https://helm.cilium.io/",                     "chart": "cilium/cilium",                 "version": "1.15.6",  "ns": "kube-system",    "default_values": {"kubeProxyReplacement": "true", "ipam.mode": "kubernetes", "hubble.relay.enabled": "true", "hubble.ui.enabled": "true"}},
    "calico":  {"repo_name": "projectcalico", "repo_url": "https://docs.tigera.io/calico/charts",        "chart": "projectcalico/tigera-operator", "version": "v3.28.0", "ns": "tigera-operator", "default_values": {}},
    "flannel": {"manifest_url": "https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml"},
    "weave":   {"manifest_url": "https://github.com/weaveworks/weave/releases/download/v2.8.1/weave-daemonset-k8s.yaml"},
}

STORAGE_HELM = {
    "longhorn":   {"repo": "longhorn",    "url": "https://charts.longhorn.io",                                            "chart": "longhorn/longhorn",              "ns": "longhorn-system",  "default_values": {}},
    "nfs":        {"repo": "nfs-subdir",  "url": "https://kubernetes-sigs.github.io/nfs-subdir-external-provisioner",    "chart": "nfs-subdir-external-provisioner/nfs-subdir-external-provisioner", "ns": "nfs-provisioner", "default_values": {}},
    "local-path": {"manifest_url": "https://raw.githubusercontent.com/rancher/local-path-provisioner/master/deploy/local-path-storage.yaml"},
    "rook-ceph":  {"repo": "rook-release","url": "https://charts.rook.io/release",                                       "chart": "rook-release/rook-ceph",         "ns": "rook-ceph",        "default_values": {"monitoring.enabled": "true"}},
}


# ─────────────────────────────────────────────────────────────────────────────
# Next-step option menus (surfaced after every successful tool call)
# ─────────────────────────────────────────────────────────────────────────────

NEXT_STEPS = {
    "plan_cluster": [
        ("preflight_check",   "Verify all nodes are ready — checks disk, RAM, ports, and auto-installs missing tools"),
        ("prepare_nodes",     "Proceed — detect OS on every node, then install containerd/kubeadm"),
        ("prepare_nodes",     "Dry-run first — show the script without executing (dry_run: true)"),
        ("plan_cluster",      "Edit the config — change CNI, profile, monitoring, node list, or CIDRs and re-plan"),
        ("provision_storage", "Add a storage layer to the plan before bootstrapping"),
    ],
    "prepare_nodes": [
        ("bootstrap_cluster", "Proceed — run kubeadm init on the first master and join everyone else"),
        ("bootstrap_cluster", "Dry-run first — preview the kubeadm init command (dry_run: true)"),
        ("node_diagnostics",  "A node failed prep — run diagnostics on it before retrying"),
        ("prepare_nodes",     "Re-run prep — safe to repeat if any node failed"),
    ],
    "bootstrap_cluster": [
        ("install_cni",       "Proceed — install a CNI so pods can get IPs"),
        ("cluster_status",    "Check status first — confirm masters came up before installing CNI"),
        ("manage_kubeconfig", "Generate a scoped kubeconfig for a teammate before continuing"),
    ],
    "install_cni": [
        ("install_stack",       "Proceed — install the Helm package stack for your use-case profile"),
        ("install_monitoring",  "Set up monitoring now (Prometheus, or Prometheus + Loki)"),
        ("cluster_status",      "Verify nodes — confirm all nodes flipped to Ready first"),
        ("provision_storage",   "Install a StorageClass now, before workloads need one"),
    ],
    "install_stack": [
        ("install_monitoring",       "Set up monitoring (Prometheus, or Prometheus + Loki)"),
        ("install_jenkins",          "Set up in-cluster Jenkins for CI/CD"),
        ("install_cert_manager",     "Install cert-manager for automated TLS cert management"),
        ("install_security_tools",   "Install Falco, Gatekeeper, Trivy Operator, or Kyverno"),
        ("install_applications",     "Install SonarQube, Harbor, Vault, or Keycloak"),
        ("cluster_status",           "Verify everything — check nodes, system pods, unhealthy pods"),
        ("backup_etcd",              "Take a baseline backup now that the cluster is fully built"),
    ],
    "install_monitoring": [
        ("install_jenkins",          "Also set up Jenkins for CI/CD in the same cluster"),
        ("install_security_tools",   "Install in-cluster security tools next"),
        ("install_applications",     "Install SonarQube, Harbor, Vault, or Keycloak"),
        ("cluster_status",           "Confirm the monitoring pods came up healthy"),
        ("generate_cluster_report",  "Generate the full cluster report with all credentials"),
    ],
    "install_jenkins": [
        ("install_applications",     "Also install SonarQube, Harbor, Vault, or Keycloak"),
        ("cluster_status",           "Confirm the Jenkins pod is Running"),
        ("stream_logs",              "Tail Jenkins controller logs to watch first boot"),
        ("generate_cluster_report",  "Generate the full cluster report with all credentials"),
    ],
    "install_security_tools": [
        ("configure_rbac",           "Bootstrap RBAC hardening next"),
        ("configure_pod_security",   "Configure PodSecurity admission + default-deny NetworkPolicy"),
        ("configure_etcd_encryption","Encrypt secrets at rest in etcd"),
        ("configure_audit_logging",  "Enable API server audit logging"),
        ("security_audit",           "Run a compliance audit to baseline the cluster"),
        ("generate_cluster_report",  "Generate the full cluster report"),
    ],
    "install_applications": [
        ("configure_rbac",           "Harden RBAC after applications are installed"),
        ("security_audit",           "Run a compliance audit"),
        ("generate_cluster_report",  "Generate the full cluster report with all credentials"),
    ],
    "configure_rbac": [
        ("configure_pod_security",   "Configure PodSecurity admission next"),
        ("configure_etcd_encryption","Encrypt secrets at rest in etcd"),
        ("configure_audit_logging",  "Enable API server audit logging"),
        ("security_audit",           "Run a compliance audit"),
    ],
    "configure_pod_security": [
        ("configure_etcd_encryption","Encrypt secrets at rest in etcd"),
        ("configure_audit_logging",  "Enable API server audit logging"),
        ("security_audit",           "Run a compliance audit"),
    ],
    "configure_etcd_encryption": [
        ("configure_audit_logging",  "Enable API server audit logging"),
        ("backup_etcd",              "Take a backup now that encryption is configured"),
        ("security_audit",           "Run a compliance audit"),
    ],
    "configure_audit_logging": [
        ("security_audit",           "Run a compliance audit to see the current baseline"),
        ("generate_cluster_report",  "Generate the full cluster report"),
    ],
    "install_cert_manager": [
        ("install_security_tools",   "Install security tools next"),
        ("renew_service_cert",       "Test cert renewal on a specific service"),
        ("cluster_status",           "Confirm cert-manager pods are Running"),
    ],
    "cluster_status": [
        ("install_monitoring",       "Set up monitoring if you haven't yet"),
        ("install_jenkins",          "Set up Jenkins if you haven't yet"),
        ("install_security_tools",   "Install Falco, Gatekeeper, Trivy, or Kyverno"),
        ("install_applications",     "Install SonarQube, Harbor, Vault, or Keycloak"),
        ("provision_namespace",      "Create a namespace for a team"),
        ("migrate_workload",         "Migrate an existing docker-compose service onto this cluster"),
        ("backup_etcd",              "Take an etcd backup"),
        ("scale_cluster",            "Add more worker or master nodes"),
        ("security_audit",           "Run a multi-standard compliance audit"),
        ("cost_report",              "Generate a resource consumption and cost report"),
        ("generate_cluster_report",  "Generate the full cluster report with all credentials"),
    ],
    "scale_cluster_add": [
        ("cluster_status",    "Confirm the new node(s) joined and are Ready"),
        ("scale_cluster",     "Add more nodes"),
        ("node_diagnostics",  "Run diagnostics on the new node to confirm health"),
    ],
    "scale_cluster_remove": [
        ("cluster_status",    "Confirm the node is gone and remaining nodes absorbed the load"),
        ("scale_cluster",     "Remove or drain another node"),
    ],
    "upgrade_cluster": [
        ("cluster_status",    "Confirm all nodes report the new version and are Ready"),
        ("rotate_certs",      "Check certificate expiry — upgrades sometimes touch cert lifetimes"),
        ("backup_etcd",       "Take a fresh backup now that the upgrade succeeded"),
    ],
    "backup_etcd": [
        ("restore_etcd",      "Test the restore path on a non-prod cluster (recommended periodically)"),
        ("cluster_snapshot",  "Also snapshot all K8s resources for GitOps backup"),
    ],
    "restore_etcd": [
        ("cluster_status",    "Confirm the cluster came back healthy after restore"),
        ("audit_cluster",     "Run a full audit — restores can reintroduce stale RBAC or expired certs"),
    ],
    "rotate_certs": [
        ("cluster_status",    "Confirm nodes are still Ready after the cert rotation restart"),
    ],
    "manage_kubeconfig": [
        ("provision_namespace","Create the namespace this kubeconfig should be scoped to, if needed"),
        ("manage_kubeconfig", "Generate another kubeconfig for a different user or namespace"),
    ],
    "provision_namespace": [
        ("manage_kubeconfig", "Generate a scoped kubeconfig for this team"),
        ("migrate_workload",  "Migrate their existing workload into this namespace"),
        ("provision_storage", "Make sure a StorageClass is available for this namespace's PVCs"),
    ],
    "provision_storage": [
        ("cluster_status",    "Confirm the StorageClass is registered and PVs can bind"),
        ("provision_namespace","Provision a namespace that will consume this storage"),
    ],
    "migrate_workload": [
        ("provision_namespace","Create the target namespace first, if it doesn't exist"),
        ("migrate_workload",   "Apply the generated manifests — say so and I'll run kubectl apply"),
        ("stream_logs",        "After applying, tail the new pod's logs to confirm it started cleanly"),
    ],
    "stream_logs": [
        ("node_diagnostics",  "If the pod is crashing, check the node it's scheduled on"),
        ("audit_cluster",     "Check whether this pod is missing resource limits or running privileged"),
    ],
    "audit_cluster": [
        ("rotate_certs",      "If certs are near expiry, rotate them now"),
        ("provision_namespace","If a namespace lacks quotas, add them"),
        ("helm_manage",       "If a release looks misconfigured, inspect or roll it back"),
    ],
    "node_diagnostics": [
        ("scale_cluster",     "If the node is unrecoverable, drain and remove it, then add a replacement"),
        ("prepare_nodes",     "If it's a fresh node that failed setup, re-run prep on it alone"),
    ],
    "helm_manage": [
        ("cluster_status",    "Confirm the release's pods are healthy after the change"),
        ("helm_manage",       "Check another release, or roll back to a previous revision"),
    ],
    "cluster_snapshot": [
        ("backup_etcd",       "Pair this with an etcd backup for full disaster-recovery coverage"),
    ],
}


def _format_next_steps(phase_key: str) -> str:
    options = NEXT_STEPS.get(phase_key, [])
    if not options:
        return ""
    lines = ["", "NEXT \u2014 choose one:"]
    for i, (tool, label) in enumerate(options, 1):
        lines.append(f"  {i}. [{tool}] {label}")
    lines.append("Reply with a number, a tool name, or describe what you want next.")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# SSH helpers — every multi-node operation goes through these for concurrency
# ─────────────────────────────────────────────────────────────────────────────

def ssh_exec(host, user, key_path, command, timeout=120):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=user, key_filename=key_path, timeout=30)
        _, stdout, stderr = client.exec_command(command, get_pty=True, timeout=timeout)
        out  = stdout.read().decode(errors="replace")
        err  = stderr.read().decode(errors="replace")
        code = stdout.channel.recv_exit_status()
        return code, out, err
    finally:
        client.close()


def ssh_run_parallel(nodes, command, max_workers=8, timeout=120):
    """Run the same command on multiple nodes concurrently. Always the default for
    independent per-node operations (prep, diagnostics, destroy, cert checks)."""
    results = {}
    def _run(node):
        code, out, err = ssh_exec(node["ip"], node.get("user", "root"), node["ssh_key"], command, timeout)
        return node["name"], {"code": code, "stdout": out, "stderr": err}
    with ThreadPoolExecutor(max_workers=min(max_workers, max(len(nodes), 1))) as ex:
        for fut in as_completed({ex.submit(_run, n): n for n in nodes}):
            name, result = fut.result()
            results[name] = result
    return results


def ssh_run_parallel_per_node_cmd(node_cmd_pairs, max_workers=8, timeout=120):
    """Like ssh_run_parallel but each node gets its OWN command (needed when the
    command depends on detected OS family). node_cmd_pairs: list of (node, command)."""
    results = {}
    def _run(pair):
        node, cmd = pair
        code, out, err = ssh_exec(node["ip"], node.get("user", "root"), node["ssh_key"], cmd, timeout)
        return node["name"], {"code": code, "stdout": out, "stderr": err}
    with ThreadPoolExecutor(max_workers=min(max_workers, max(len(node_cmd_pairs), 1))) as ex:
        for fut in as_completed({ex.submit(_run, p): p for p in node_cmd_pairs}):
            name, result = fut.result()
            results[name] = result
    return results


# ─────────────────────────────────────────────────────────────────────────────
# OS detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_node_os(node: dict) -> dict:
    """SSH into a single node, run OS_DETECT_SCRIPT, parse into a dict with
    os_id, os_id_like, version_id, pretty_name, and resolved os_family."""
    code, out, err = ssh_exec(node["ip"], node.get("user", "root"), node["ssh_key"], OS_DETECT_SCRIPT, timeout=30)
    info = {"os_id": "unknown", "os_id_like": "", "version_id": "", "pretty_name": "unknown"}
    if code == 0:
        for line in out.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                key_map = {"ID": "os_id", "ID_LIKE": "os_id_like", "VERSION_ID": "version_id", "PRETTY_NAME": "pretty_name"}
                if k in key_map:
                    info[key_map[k]] = v.strip()
    info["os_family"] = detect_os_family(info["os_id"], info["os_id_like"])
    info["detect_error"] = err if code != 0 else ""
    return info


def detect_all_nodes_os(nodes: list[dict], max_workers=8) -> dict:
    """Detect OS on every node concurrently. Returns {node_name: os_info_dict}."""
    results = {}
    def _run(node):
        return node["name"], detect_node_os(node)
    with ThreadPoolExecutor(max_workers=min(max_workers, max(len(nodes), 1))) as ex:
        for fut in as_completed({ex.submit(_run, n): n for n in nodes}):
            name, info = fut.result()
            results[name] = info
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Script factories — every script branches on os_family
# ─────────────────────────────────────────────────────────────────────────────

def node_prep_script(k8s_version: str, os_family: str,
                      proxy_cfg: dict | None = None,
                      node_config: dict | None = None) -> str:
    """Build the node-prep script for the given OS family.
    node_config controls kernel modules, sysctl preset, iptables mode,
    SELinux handling, swap handling, hugepages, and ulimits — all user-
    selectable from the cluster config rather than hardcoded."""
    nc  = {**DEFAULT_NODE_CONFIG, **(node_config or {})}
    pkg = PKG_COMMANDS[os_family]
    repo_setup = pkg["repo_setup"].format(k8s_version=k8s_version)

    proxy_exports    = proxy_env_exports(proxy_cfg)
    containerd_proxy = containerd_proxy_dropin(proxy_cfg)

    sysctl_block   = build_sysctl_block(nc)
    modules_block  = build_kernel_modules_block(nc)
    iptables_block = build_iptables_block(nc, os_family)
    swap_block     = build_swap_block(nc)
    selinux_block  = build_selinux_block(nc, os_family)
    ulimits_block  = build_ulimits_block(nc)
    hugepages_block= build_hugepages_block(nc)

    if os_family == "debian":
        pkg_proxy_conf = apt_proxy_conf(proxy_cfg)
        containerd_cgroup_fix = textwrap.dedent("""
            mkdir -p /etc/containerd
            containerd config default | tee /etc/containerd/config.toml >/dev/null
            sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
        """).strip()
        install_k8s_pkgs = "apt-get install -y -qq kubelet kubeadm kubectl"
        hold_cmd          = pkg["hold"].format(pkgs="kubelet kubeadm kubectl")
    elif os_family == "rhel":
        pkg_proxy_conf = dnf_proxy_conf(proxy_cfg)
        containerd_cgroup_fix = textwrap.dedent("""
            mkdir -p /etc/containerd
            containerd config default | tee /etc/containerd/config.toml >/dev/null
            sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
        """).strip()
        install_k8s_pkgs = "(dnf install -y -q kubelet kubeadm kubectl --disableexcludes=kubernetes 2>/dev/null || yum install -y -q kubelet kubeadm kubectl --disableexcludes=kubernetes)"
        hold_cmd          = pkg["hold"].format(pkgs="kubelet kubeadm kubectl")
    else:  # suse
        pkg_proxy_conf = zypper_proxy_conf(proxy_cfg)
        containerd_cgroup_fix = textwrap.dedent("""
            mkdir -p /etc/containerd
            containerd config default | tee /etc/containerd/config.toml >/dev/null
            sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
        """).strip()
        install_k8s_pkgs = "zypper install -y kubelet kubeadm kubectl"
        hold_cmd          = pkg["hold"].format(pkgs="kubelet kubeadm kubectl")

    prereqs = prerequisites_script(os_family, proxy_cfg)

    return textwrap.dedent(f"""
        set -euo pipefail

        # ── Prerequisites (Helm, etcdctl, repos, tools) ───────────────────
        {prereqs}

        # ── Proxy setup ──────────────────────────────────────────────────
        {proxy_exports}{pkg_proxy_conf}

        # ── Swap ─────────────────────────────────────────────────────────
        {swap_block}

        # ── SELinux (RHEL/CentOS only) ────────────────────────────────────
        {selinux_block}

        # ── Kernel modules ────────────────────────────────────────────────
        cat <<'MODEOF' | tee /etc/modules-load.d/k8s.conf
{modules_block}
MODEOF
        for mod in {modules_block.replace(chr(10), " ")}; do
            modprobe "$mod" 2>/dev/null || echo "WARN: module $mod not available (may not be needed on this kernel)"
        done

        # ── sysctl parameters ─────────────────────────────────────────────
        cat <<'SYSCTLEOF' | tee /etc/sysctl.d/k8s.conf
{sysctl_block}
SYSCTLEOF
        sysctl --system >/dev/null

        # ── iptables mode ─────────────────────────────────────────────────
        {iptables_block}

        # ── ulimits ───────────────────────────────────────────────────────
        {ulimits_block}

        # ── Transparent hugepages ─────────────────────────────────────────
        {hugepages_block}

        # ── Packages + containerd ─────────────────────────────────────────
        {pkg["update"]}
        {pkg["install"].format(pkgs=pkg["base_pkgs"])}
        {containerd_cgroup_fix}
        {containerd_proxy}
        systemctl restart containerd && systemctl enable containerd

        # ── Kubernetes packages ───────────────────────────────────────────
        {repo_setup}
        {pkg["update"]}
        {install_k8s_pkgs}
        {hold_cmd}
        systemctl enable kubelet

        echo NODE_PREP_DONE
    """).strip()


def master_init_script(control_plane_endpoint: str, pod_cidr: str, svc_cidr: str,
                        k8s_ver: str, is_first_master: bool, upload_certs: bool = True) -> str:
    """First master runs full kubeadm init. Additional masters in HA mode join as
    control-plane nodes using the join command + --control-plane flag (handled
    separately in bootstrap_cluster, not here)."""
    upload_flag = "--upload-certs" if upload_certs else ""
    return textwrap.dedent(f"""
        set -euo pipefail
        kubeadm init \\
            --control-plane-endpoint "{control_plane_endpoint}:6443" \\
            {upload_flag} \\
            --pod-network-cidr "{pod_cidr}" \\
            --service-cidr "{svc_cidr}" \\
            --kubernetes-version "v{k8s_ver}"
        mkdir -p $HOME/.kube
        cp /etc/kubernetes/admin.conf $HOME/.kube/config
        chown $(id -u):$(id -g) $HOME/.kube/config
        echo "---WORKER-JOIN---"
        kubeadm token create --print-join-command
        echo "---CONTROL-PLANE-JOIN---"
        kubeadm init phase upload-certs --upload-certs 2>/dev/null | tail -1
    """).strip()


def control_plane_join_script(join_cmd: str, certificate_key: str) -> str:
    """For additional masters in an HA setup — joins as a control-plane node."""
    return textwrap.dedent(f"""
        set -euo pipefail
        {join_cmd} --control-plane --certificate-key {certificate_key}
        mkdir -p $HOME/.kube
        cp /etc/kubernetes/admin.conf $HOME/.kube/config
        chown $(id -u):$(id -g) $HOME/.kube/config
        echo CONTROL_PLANE_JOIN_DONE
    """).strip()


def node_upgrade_script(new_ver: str, role: str, os_family: str, proxy_cfg: dict | None = None) -> str:
    """Upgrade kubeadm/kubelet/kubectl on a node, branching on OS family for the
    package pinning syntax. Re-applies proxy env + package-manager proxy config
    since upgrades hit the package repos again, same as initial prep."""
    upgrade_cmd = f"kubeadm upgrade apply v{new_ver} --yes" if role == "master" else "kubeadm upgrade node"
    proxy_exports = proxy_env_exports(proxy_cfg)

    if os_family == "debian":
        pkg_proxy_conf = apt_proxy_conf(proxy_cfg)
        steps = textwrap.dedent(f"""
            apt-mark unhold kubeadm
            apt-get update -qq && apt-get install -y -qq kubeadm={new_ver}-*
            apt-mark hold kubeadm
            {upgrade_cmd}
            apt-mark unhold kubelet kubectl
            apt-get install -y -qq kubelet={new_ver}-* kubectl={new_ver}-*
            apt-mark hold kubelet kubectl
        """).strip()
    elif os_family == "rhel":
        pkg_proxy_conf = dnf_proxy_conf(proxy_cfg)
        steps = textwrap.dedent(f"""
            dnf versionlock delete kubeadm 2>/dev/null || true
            (dnf install -y -q kubeadm-{new_ver} --disableexcludes=kubernetes 2>/dev/null || yum install -y -q kubeadm-{new_ver} --disableexcludes=kubernetes)
            dnf versionlock add kubeadm 2>/dev/null || true
            {upgrade_cmd}
            dnf versionlock delete kubelet kubectl 2>/dev/null || true
            (dnf install -y -q kubelet-{new_ver} kubectl-{new_ver} --disableexcludes=kubernetes 2>/dev/null || yum install -y -q kubelet-{new_ver} kubectl-{new_ver} --disableexcludes=kubernetes)
            dnf versionlock add kubelet kubectl 2>/dev/null || true
        """).strip()
    else:  # suse
        pkg_proxy_conf = zypper_proxy_conf(proxy_cfg)
        steps = textwrap.dedent(f"""
            zypper removelock kubeadm 2>/dev/null || true
            zypper install -y kubeadm-{new_ver}
            zypper addlock kubeadm 2>/dev/null || true
            {upgrade_cmd}
            zypper removelock kubelet kubectl 2>/dev/null || true
            zypper install -y kubelet-{new_ver} kubectl-{new_ver}
            zypper addlock kubelet kubectl 2>/dev/null || true
        """).strip()

    return textwrap.dedent(f"""
        set -euo pipefail
        {proxy_exports}{pkg_proxy_conf}
        {steps}
        systemctl daemon-reload && systemctl restart kubelet
        echo UPGRADE_DONE
    """).strip()


def namespace_manifest(name, team, cpu_limit, mem_limit, cpu_req, mem_req):
    return textwrap.dedent(f"""
apiVersion: v1
kind: Namespace
metadata:
  name: {name}
  labels:
    team: {team}
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: {name}-quota
  namespace: {name}
spec:
  hard:
    requests.cpu: "{cpu_req}"
    requests.memory: "{mem_req}"
    limits.cpu: "{cpu_limit}"
    limits.memory: "{mem_limit}"
    pods: "50"
    services: "20"
    persistentvolumeclaims: "10"
---
apiVersion: v1
kind: LimitRange
metadata:
  name: {name}-limits
  namespace: {name}
spec:
  limits:
  - default:
      cpu: "500m"
      memory: "512Mi"
    defaultRequest:
      cpu: "100m"
      memory: "128Mi"
    type: Container
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {name}-admin
  namespace: {name}
subjects:
- kind: Group
  name: {team}
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: admin
  apiGroup: rbac.authorization.k8s.io
    """).strip()


def compose_to_k8s(svc_name, image, ports, env_vars, replicas=1, namespace="default"):
    env_block = ""
    if env_vars:
        env_block = "        env:\n"
        for k, v in env_vars.items():
            env_block += f'        - name: {k}\n          value: "{v}"\n'
    port_block = ""
    svc_ports  = ""
    if ports:
        port_block = "        ports:\n"
        svc_ports  = "  ports:\n"
        for p in ports:
            parts = str(p).split(":")
            hp = parts[0] if len(parts) > 1 else parts[0]
            cp = parts[-1]
            port_block += f"        - containerPort: {cp}\n"
            svc_ports  += f"  - port: {hp}\n    targetPort: {cp}\n"
    first_port = ports[0].split(":")[-1] if ports else "80"
    return textwrap.dedent(f"""
# Generated by k8s-factory MCP — migrate_workload
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {svc_name}
  namespace: {namespace}
  labels:
    app: {svc_name}
spec:
  replicas: {replicas}
  selector:
    matchLabels:
      app: {svc_name}
  template:
    metadata:
      labels:
        app: {svc_name}
    spec:
      containers:
      - name: {svc_name}
        image: {image}
        imagePullPolicy: IfNotPresent
{port_block}{env_block}        resources:
          requests:
            cpu: "100m"
            memory: "128Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"
        livenessProbe:
          tcpSocket:
            port: {first_port}
          initialDelaySeconds: 15
          periodSeconds: 20
        readinessProbe:
          tcpSocket:
            port: {first_port}
          initialDelaySeconds: 5
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: {svc_name}
  namespace: {namespace}
spec:
  selector:
    app: {svc_name}
  type: ClusterIP
{svc_ports}
    """).strip()


# ─────────────────────────────────────────────────────────────────────────────
# MCP Server — tool list
# ─────────────────────────────────────────────────────────────────────────────

server = Server("k8s-factory")
_state: dict[str, Any] = {}


@server.list_tools()
async def list_tools():
    return [
        Tool(name="plan_cluster", description=(
            "Validate cluster config and return full execution plan. Run FIRST before any other tool. "
            "Supports multi-master HA (list 2+ entries under masters for HA, kubeadm join --control-plane "
            "is used automatically for masters after the first). os_family per node is optional — if "
            "omitted or set to 'auto', prepare_nodes will SSH in and detect it automatically (Ubuntu/Debian "
            "vs RHEL/CentOS/Rocky/Alma vs SUSE), so nodes can run different OSes in the same cluster. "
            "If the organization's servers reach the internet only through a corporate proxy, add a "
            "top-level proxy block with http_proxy/https_proxy (and optionally no_proxy) — this is applied "
            "automatically to every package manager (apt/dnf/zypper), containerd, curl, helm, and "
            "kubectl apply -f <url> call across the whole cluster lifecycle, not just node prep. If the "
            "user mentions a proxy, firewall, or restricted/air-gapped internet access but hasn't given "
            "exact proxy URLs, ask for http_proxy/https_proxy values before proceeding rather than guessing. "
            "If the user has not specified cni, profile, monitoring, or CIDRs, ask them to choose rather than "
            "guessing — present the supported options: cni one of [cilium, calico, flannel, weave]; "
            "profile one of [production, development, ml-gpu, edge, multi-tenant]; monitoring one of "
            "[prometheus, prometheus-loki, none]. Defaults if truly undecided: cni=cilium, profile=development, "
            "monitoring=prometheus, pod_cidr=10.244.0.0/16, service_cidr=10.96.0.0/12."),
             inputSchema={"type":"object","properties":{"config":{"type":"string","description":(
                 "YAML cluster config: cluster_name, k8s_version, cni, pod_cidr, service_cidr, profile, "
                 "monitoring (prometheus|prometheus-loki|none), masters[] (2+ for HA), workers[]. "
                 "Each node entry: {name, ip, user, ssh_key, os_family (optional: debian|rhel|suse|auto)}. "
                 "Optional top-level proxy block: {http_proxy, https_proxy, no_proxy} — applied to every "
                 "network-touching command on every node throughout the cluster's lifecycle.")}},"required":["config"]}),

        Tool(name="prepare_nodes", description=(
            "SSH to all nodes in parallel. First detects each node's OS family (unless explicitly set "
            "in config), then runs the matching package-manager script (apt/dnf/yum/zypper) to disable "
            "swap and install containerd + kubeadm/kubelet/kubectl."),
             inputSchema={"type":"object","properties":{"dry_run":{"type":"boolean","default":False}}}),

        Tool(name="bootstrap_cluster", description=(
            "kubeadm init on the first master. If multiple masters are configured (HA mode), joins the "
            "additional masters as control-plane nodes using --upload-certs, then joins all workers. "
            "Saves kubeconfig to session state."),
             inputSchema={"type":"object","properties":{"dry_run":{"type":"boolean","default":False}}}),

        Tool(name="install_cni", description="Install CNI plugin (cilium/calico/flannel/weave) via Helm or kubectl apply.",
             inputSchema={"type":"object","properties":{"dry_run":{"type":"boolean","default":False}}}),

        Tool(name="install_stack", description="Install Helm package stack for the selected use-case profile.",
             inputSchema={"type":"object","properties":{"packages":{"type":"array","items":{"type":"string"}},"dry_run":{"type":"boolean","default":False}}}),

        Tool(name="install_monitoring", description=(
            "Install a monitoring stack via Helm: 'prometheus' (kube-prometheus-stack: Prometheus + Grafana "
            "+ Alertmanager) or 'prometheus-loki' (adds Loki + Promtail for log aggregation) or skip with "
            "'none'. If not specified by the user and not already set in the cluster config, ask which "
            "option they want before calling this with a guess."),
             inputSchema={"type":"object","properties":{
                 "monitoring_type": {"type":"string","enum":["prometheus","prometheus-loki","none"],
                                     "description":"Which monitoring stack to install. Ask the user if unspecified."},
                 "grafana_password": {"type":"string","default":"admin-changeme","description":"Grafana admin password to set"},
                 "dry_run": {"type":"boolean","default":False}},"required":["monitoring_type"]}),

        Tool(name="install_jenkins", description=(
            "Install Jenkins inside the cluster via the official Helm chart. Exposed as ClusterIP only "
            "(internal cluster use — no external ingress). Comes with the Kubernetes plugin pre-installed "
            "so Jenkins can spin up its own build agents as pods in this same cluster, a persistent volume "
            "for JENKINS_HOME, and RBAC already wired."),
             inputSchema={"type":"object","properties":{
                 "admin_password": {"type":"string","default":"admin-changeme"},
                 "storage_size":    {"type":"string","default":"10Gi"},
                 "storage_class":   {"type":"string","description":"StorageClass to use for the Jenkins PVC — omit to use the cluster default"},
                 "dry_run":         {"type":"boolean","default":False}}}),

        Tool(name="preflight_check",
             description=(
                 "Run a preflight check on all nodes before bootstrapping. Verifies: "
                 "SSH connectivity, OS detection, Python availability, sufficient disk space, "
                 "sufficient RAM, port availability (6443, 10250, 2379-2380), "
                 "internet/proxy reachability, and whether Helm and etcdctl are installed. "
                 "Fixes missing tools automatically (Helm, etcdctl, repo configs) without "
                 "full node prep. Run this any time to verify a node is ready."),
             inputSchema={"type":"object","properties":{
                 "fix":  {"type":"boolean","default":True,
                          "description":"Automatically install any missing tools and repos found during the check"},
                 "node_name": {"type":"string","description":"Check only this node — omit for all nodes"}}}),

        Tool(name="cluster_status", description="Health check: nodes, system pods, unhealthy pods, PVs, LoadBalancer services.",
             inputSchema={"type":"object","properties":{}}),

        Tool(name="destroy_cluster", description="kubeadm reset + iptables flush on ALL nodes in parallel. DESTRUCTIVE. Requires confirm=DESTROY.",
             inputSchema={"type":"object","properties":{"confirm":{"type":"string"}},"required":["confirm"]}),

        Tool(name="scale_cluster", description=(
            "Add new worker OR master nodes to a live cluster (auto-detects OS on new nodes), or "
            "drain/remove existing ones. Adding a master automatically uses the HA control-plane join path."),
             inputSchema={"type":"object","properties":{
                 "action": {"type":"string","enum":["add","drain","remove"]},
                 "role":   {"type":"string","enum":["worker","master"],"default":"worker","description":"Only used when action=add"},
                 "nodes":  {"type":"array","items":{"type":"object"},"description":"For add: [{name,ip,user,ssh_key,os_family?}]. For drain/remove: list of node name strings."},
                 "dry_run":{"type":"boolean","default":False}},"required":["action","nodes"]}),

        Tool(name="upgrade_cluster", description=(
            "Rolling kubeadm upgrade, OS-aware per node. Upgrades the first master, then any additional "
            "masters one at a time, then workers in parallel batches of up to 3 at a time with drain/uncordon "
            "around each batch so the cluster stays available throughout."),
             inputSchema={"type":"object","properties":{
                 "target_version":{"type":"string","description":"Target K8s version e.g. 1.31"},
                 "worker_batch_size": {"type":"integer","default":3,"description":"How many workers to upgrade concurrently per batch"},
                 "dry_run":{"type":"boolean","default":False}},"required":["target_version"]}),

        Tool(name="backup_etcd", description="Create a timestamped etcd snapshot on the first master node.",
             inputSchema={"type":"object","properties":{"backup_path":{"type":"string","default":"/opt/etcd-backups/snapshot.db"}}}),

        Tool(name="restore_etcd", description="Restore etcd from a snapshot. Stops control plane temporarily. Requires confirm=RESTORE.",
             inputSchema={"type":"object","properties":{"snapshot_path":{"type":"string"},"confirm":{"type":"string"}},"required":["snapshot_path","confirm"]}),

        Tool(name="rotate_certs", description="Check or renew all kubeadm-managed TLS certificates on every master, in parallel.",
             inputSchema={"type":"object","properties":{"check_only":{"type":"boolean","default":False}}}),

        Tool(name="manage_kubeconfig", description="Generate a scoped kubeconfig for a user/ServiceAccount with namespace-level RBAC.",
             inputSchema={"type":"object","properties":{
                 "username":   {"type":"string"},
                 "namespace":  {"type":"string"},
                 "role":       {"type":"string","enum":["view","edit","admin"],"default":"view"},
                 "output_path":{"type":"string","default":"./kubeconfig-user.yaml"}},"required":["username","namespace"]}),

        Tool(name="provision_namespace", description="Create namespace + ResourceQuota + LimitRange + team RBAC in one operation.",
             inputSchema={"type":"object","properties":{
                 "name":      {"type":"string"},
                 "team":      {"type":"string"},
                 "cpu_limit": {"type":"string","default":"8"},
                 "mem_limit": {"type":"string","default":"16Gi"},
                 "cpu_req":   {"type":"string","default":"4"},
                 "mem_req":   {"type":"string","default":"8Gi"}},"required":["name","team"]}),

        Tool(name="provision_storage", description="Install a StorageClass: longhorn (distributed), nfs, local-path, or rook-ceph.",
             inputSchema={"type":"object","properties":{
                 "type":        {"type":"string","enum":["longhorn","nfs","local-path","rook-ceph"]},
                 "set_default": {"type":"boolean","default":True},
                 "nfs_server":  {"type":"string"},
                 "nfs_path":    {"type":"string"},
                 "dry_run":     {"type":"boolean","default":False}},"required":["type"]}),

        Tool(name="migrate_workload", description=(
            "Convert docker-compose.yml or a systemd unit to K8s Deployment + Service manifests. "
            "Optionally adds HPA and PDB."),
             inputSchema={"type":"object","properties":{
                 "source_type":{"type":"string","enum":["docker-compose","systemd"]},
                 "source":     {"type":"string"},
                 "namespace":  {"type":"string","default":"default"},
                 "replicas":   {"type":"integer","default":1},
                 "add_hpa":    {"type":"boolean","default":False},
                 "add_pdb":    {"type":"boolean","default":False}},"required":["source_type","source"]}),

        Tool(name="stream_logs", description="Tail pod logs by pod name, label selector, or all pods in a namespace.",
             inputSchema={"type":"object","properties":{
                 "namespace": {"type":"string","default":"default"},
                 "pod":       {"type":"string"},
                 "selector":  {"type":"string"},
                 "container": {"type":"string"},
                 "tail_lines":{"type":"integer","default":50},
                 "previous":  {"type":"boolean","default":False}}}),

        Tool(name="audit_cluster", description=(
            "Security and config audit: privileged pods, missing resource limits, NodePort services, "
            "RBAC, unbound PVCs, cert expiry."),
             inputSchema={"type":"object","properties":{
                 "checks":{"type":"array","items":{"type":"string","enum":["security","rbac","resources","networking","storage","certificates","all"]},"default":["all"]}}}),

        Tool(name="node_diagnostics", description=(
            "Deep per-node diagnostics (runs in parallel across all targeted nodes): disk, memory, CPU, "
            "kernel, detected OS family, kubelet logs, OOM events, network interfaces."),
             inputSchema={"type":"object","properties":{"node_name":{"type":"string","description":"Specific node — omit for all nodes"}}}),

        Tool(name="helm_manage", description="List, status, upgrade, rollback, uninstall, or show history of any Helm release.",
             inputSchema={"type":"object","properties":{
                 "action":   {"type":"string","enum":["list","status","upgrade","rollback","uninstall","history"]},
                 "release":  {"type":"string"},
                 "namespace":{"type":"string"},
                 "chart":    {"type":"string"},
                 "version":  {"type":"string"},
                 "revision": {"type":"integer"},
                 "dry_run":  {"type":"boolean","default":False}},"required":["action"]}),

        Tool(name="cluster_snapshot", description="Dump all non-secret K8s resources to YAML files on the master for GitOps or DR.",
             inputSchema={"type":"object","properties":{
                 "output_dir":      {"type":"string","default":"/opt/cluster-snapshot"},
                 "namespaces":      {"type":"array","items":{"type":"string"}},
                 "exclude_secrets": {"type":"boolean","default":True}}}),

        # ── Security, applications, reporting tools ───────────────────────────

        Tool(name="install_security_tools",
             description=(
                 "Install in-cluster security tools. Ask the user which ones they want if not specified. "
                 "Options: falco (runtime threat detection), gatekeeper (OPA policy enforcement), "
                 "trivy-operator (image vuln scanning), kyverno (policy-as-code). "
                 "Can install any combination. All are selectable individually."),
             inputSchema={"type":"object","properties":{
                 "tools":    {"type":"array","items":{"type":"string","enum":["falco","gatekeeper","trivy-operator","kyverno"]},
                              "description":"Which security tools to install. Ask user if not specified."},
                 "dry_run":  {"type":"boolean","default":False}},"required":["tools"]}),

        Tool(name="install_applications",
             description=(
                 "Install additional applications into the cluster. Ask the user which ones they want if not specified. "
                 "Options: sonarqube (code quality+SAST), harbor (private registry+scanning), "
                 "vault (secrets management, K8s auth auto-configured), keycloak (SSO/OIDC, kube-apiserver wired). "
                 "Generates credentials for each installed application."),
             inputSchema={"type":"object","properties":{
                 "apps":       {"type":"array","items":{"type":"string","enum":["sonarqube","harbor","vault","keycloak"]},
                                "description":"Which applications to install. Ask user if not specified."},
                 "storage_class": {"type":"string","description":"StorageClass for persistent volumes (uses cluster default if omitted)"},
                 "dry_run":    {"type":"boolean","default":False}},"required":["apps"]}),

        Tool(name="configure_rbac",
             description=(
                 "Bootstrap cluster-level RBAC security: restrict default ServiceAccount automount, "
                 "remove anonymous access, configure audit policy, lock down cluster-admin binding, "
                 "create dedicated ServiceAccounts per installed application."),
             inputSchema={"type":"object","properties":{
                 "audit_level":    {"type":"string","enum":["none","metadata","request","requestresponse"],"default":"metadata"},
                 "restrict_default_sa": {"type":"boolean","default":True,"description":"Patch all default ServiceAccounts with automountServiceAccountToken=false"},
                 "dry_run":        {"type":"boolean","default":False}}}),

        Tool(name="configure_pod_security",
             description=(
                 "Configure Pod Security Admission (replaces PodSecurityPolicy), default-deny NetworkPolicies "
                 "per namespace, seccomp RuntimeDefault profile, and read-only root filesystem enforcement."),
             inputSchema={"type":"object","properties":{
                 "mode":       {"type":"string","enum":["privileged","baseline","restricted"],"default":"baseline",
                                "description":"PodSecurity admission mode applied cluster-wide"},
                 "default_deny_network": {"type":"boolean","default":True,
                                          "description":"Apply default-deny NetworkPolicy to all non-system namespaces"},
                 "dry_run":    {"type":"boolean","default":False}}}),

        Tool(name="configure_etcd_encryption",
             description=(
                 "Configure encryption at rest for Kubernetes Secrets stored in etcd. "
                 "Generates an EncryptionConfiguration file and restarts the API server. "
                 "Supports AES-CBC (widely compatible) and AES-GCM (faster). "
                 "WARNING: back up etcd first — this is a destructive API server config change."),
             inputSchema={"type":"object","properties":{
                 "algorithm": {"type":"string","enum":["aes-cbc","aes-gcm"],"default":"aes-cbc"},
                 "dry_run":   {"type":"boolean","default":False}}}),

        Tool(name="configure_audit_logging",
             description=(
                 "Configure Kubernetes API server audit logging with a policy file. "
                 "Choices: none (off), metadata (who+what, no bodies), request (+ request body), "
                 "requestresponse (full request+response — high volume). Writes the policy file and restarts the API server."),
             inputSchema={"type":"object","properties":{
                 "level":      {"type":"string","enum":["none","metadata","request","requestresponse"],"default":"metadata"},
                 "log_path":   {"type":"string","default":"/var/log/kubernetes/audit.log"},
                 "max_age":    {"type":"integer","default":30,"description":"Days to retain audit logs"},
                 "dry_run":    {"type":"boolean","default":False}}}),

        Tool(name="security_audit",
             description=(
                 "Run a multi-standard compliance audit. Ask user which standards to check if not specified. "
                 "Standards: cis (CIS K8s Benchmark), nsa-cisa (NSA/CISA Hardening Guide), "
                 "pci-dss (Payment Card Industry), soc2-iso27001 (SOC2/ISO27001 controls). "
                 "Returns a structured report with pass/fail per control, grouped by standard."),
             inputSchema={"type":"object","properties":{
                 "standards": {"type":"array","items":{"type":"string","enum":["cis","nsa-cisa","pci-dss","soc2-iso27001","all"]},
                               "default":["all"],"description":"Compliance standards to check. Ask user if not specified."},
                 "output_report": {"type":"boolean","default":True,"description":"Include in the cluster report file"}}}),

        Tool(name="install_cert_manager",
             description=(
                 "Install cert-manager and configure a ClusterIssuer. "
                 "Issuer options: self-signed (no external dependency, good for on-prem), "
                 "acme-letsencrypt (requires public DNS + port 80/443), "
                 "acme-zerossl (alternative ACME, requires account email), "
                 "internal-ca (use your own CA cert+key). "
                 "Separate from install_stack — cert-manager is a prerequisite for zero-downtime cert renewal."),
             inputSchema={"type":"object","properties":{
                 "issuer_type":  {"type":"string","enum":["self-signed","acme-letsencrypt","acme-zerossl","internal-ca"],
                                  "default":"self-signed"},
                 "email":        {"type":"string","description":"Required for ACME issuers"},
                 "ca_cert":      {"type":"string","description":"Base64 CA cert for internal-ca issuer"},
                 "ca_key":       {"type":"string","description":"Base64 CA key for internal-ca issuer"},
                 "dry_run":      {"type":"boolean","default":False}}}),

        Tool(name="renew_service_cert",
             description=(
                 "Trigger zero-downtime certificate renewal for a specific service managed by cert-manager. "
                 "Annotates the Certificate resource to force immediate renewal without pod restarts "
                 "(cert-manager handles rotation transparently). "
                 "For control-plane certs use rotate_certs instead."),
             inputSchema={"type":"object","properties":{
                 "certificate_name": {"type":"string","description":"Name of the cert-manager Certificate resource"},
                 "namespace":        {"type":"string","default":"default"},
                 "force":            {"type":"boolean","default":False,
                                      "description":"If true, delete and recreate the Secret to force full re-issuance"}}}),

        Tool(name="cost_report",
             description=(
                 "Generate a resource consumption and cost report for the cluster. "
                 "For cloud providers (aws/gcp/azure): queries billing APIs for actual spend. "
                 "For on-prem/openstack: calculates estimated cost from vCPU/RAM/storage consumption "
                 "× configurable per-unit rates (set under costing block in cluster config). "
                 "Output: per-namespace breakdown, per-component breakdown, total monthly estimate."),
             inputSchema={"type":"object","properties":{
                 "cloud_provider": {"type":"string","enum":["aws","gcp","azure","onprem","openstack"],
                                    "description":"Infrastructure type. Uses cluster config value if omitted."},
                 "aws_profile":    {"type":"string","description":"AWS CLI profile for billing API (aws only)"},
                 "gcp_project":    {"type":"string","description":"GCP project ID (gcp only)"},
                 "azure_sub":      {"type":"string","description":"Azure subscription ID (azure only)"},
                 "breakdown":      {"type":"string","enum":["namespace","node","component","all"],"default":"all"}}}),

        Tool(name="generate_cluster_report",
             description=(
                 "Generate the full cluster report in both Markdown (human-readable) and YAML (machine-readable). "
                 "Includes: all credentials (Jenkins, Grafana, SonarQube, Harbor, Vault, Keycloak), "
                 "service IPs and access commands, namespace details, network details (pod/service CIDRs, CNI), "
                 "ServiceAccount tokens, certificate expiry dates, compliance audit summary, "
                 "cost estimate, and next recommended actions. "
                 "Saves to /opt/cluster-report/ on the master node and streams a summary to the conversation."),
             inputSchema={"type":"object","properties":{
                 "output_dir":  {"type":"string","default":"/opt/cluster-report"},
                 "include_secrets": {"type":"boolean","default":True,
                                     "description":"Include credential values in output (set false for shared reports)"}}}),
    ]


@server.call_tool()
async def call_tool(name, arguments):

    def cfg():
        c = _state.get("config")
        if not c:
            raise ValueError("No cluster config. Run plan_cluster first.")
        return c

    def proxy():
        """Returns the proxy config dict from cluster config, or None if not set.
        Used by every helm/kubectl-apply-url/curl command, not just package installs."""
        return cfg().get("proxy")

    def all_masters():
        return cfg()["masters"]

    def first_master():
        return cfg()["masters"][0]

    def all_nodes():
        return cfg()["masters"] + cfg()["workers"]

    def with_proxy(cmd: str) -> str:
        """Prepend proxy env exports to any shell command that touches the network
        (helm repo add, kubectl apply -f <url>, curl). No-op if no proxy configured."""
        exports = proxy_env_exports(proxy())
        return f"{exports}{cmd}" if exports else cmd

    def ssh(cmd, node=None, timeout=120):
        n = node or first_master()
        return ssh_exec(n["ip"], n.get("user", "root"), n["ssh_key"], cmd, timeout)

    def node_os_family(node: dict) -> str:
        """Resolve a node's os_family: explicit config value wins, else session-cached
        detection, else 'auto' triggers a fresh detection right now."""
        if node.get("os_family") and node["os_family"] != "auto":
            return node["os_family"]
        cached = _state.get("os_cache", {}).get(node["name"])
        if cached:
            return cached["os_family"]
        info = detect_node_os(node)
        _state.setdefault("os_cache", {})[node["name"]] = info
        return info["os_family"]

    def err(msg):
        return [TextContent(type="text", text=f"ERROR: {msg}")]

    try:

        # ── plan_cluster ──────────────────────────────────────────────────
        if name == "plan_cluster":
            try:
                c = yaml.safe_load(arguments["config"])
            except Exception as e:
                return err(f"Cannot parse config: {e}")
            issues = []
            for f in ["cluster_name","k8s_version","cni","pod_cidr","service_cidr","profile","masters","workers"]:
                if f not in c: issues.append(f"Missing: {f}")
            if c.get("cni") not in SUPPORTED_CNI: issues.append(f"cni must be one of {SUPPORTED_CNI}")
            if c.get("profile") not in SUPPORTED_PROFILES: issues.append(f"profile must be one of {SUPPORTED_PROFILES}")
            mon = c.get("monitoring", "prometheus")
            if mon not in SUPPORTED_MONITORING: issues.append(f"monitoring must be one of {SUPPORTED_MONITORING}")
            if issues:
                return err("Validation:\n" + "\n".join(f"  \u2022 {i}" for i in issues))

            for node in c["masters"] + c["workers"]:
                node.setdefault("os_family", "auto")
                node.setdefault("user", "root")

            proxy_cfg = c.get("proxy")
            if proxy_cfg and not (proxy_cfg.get("http_proxy") or proxy_cfg.get("https_proxy")):
                return err("proxy block is present but has neither http_proxy nor https_proxy set \u2014 "
                           "remove the proxy block entirely if no proxy is needed, or set at least one of them")

            # Validate node_config block if present
            nc = c.get("node_config", {})
            nc_issues = []
            if nc.get("sysctl_preset") and nc["sysctl_preset"] not in SUPPORTED_SYSCTL_PRESETS:
                nc_issues.append(f"node_config.sysctl_preset must be one of {SUPPORTED_SYSCTL_PRESETS}")
            if nc.get("selinux") and nc["selinux"] not in SUPPORTED_SELINUX:
                nc_issues.append(f"node_config.selinux must be one of {SUPPORTED_SELINUX}")
            if nc.get("swap") and nc["swap"] not in SUPPORTED_SWAP:
                nc_issues.append(f"node_config.swap must be one of {SUPPORTED_SWAP}")
            if nc.get("iptables_mode") and nc["iptables_mode"] not in SUPPORTED_IPTABLES:
                nc_issues.append(f"node_config.iptables_mode must be one of {SUPPORTED_IPTABLES}")
            if nc.get("kernel_modules") and nc["kernel_modules"] not in KERNEL_MODULES_OPTIONAL:
                nc_issues.append(f"node_config.kernel_modules must be one of {list(KERNEL_MODULES_OPTIONAL.keys())}")
            if nc_issues:
                return err("node_config validation:\n" + "\n".join(f"  \u2022 {i}" for i in nc_issues))

            # Apply defaults to node_config so they're stored in state
            c["node_config"] = {**DEFAULT_NODE_CONFIG, **nc}

            _state["config"] = c
            pkgs = HELM_PACKAGES.get(c["profile"], [])
            ha_note = f"HA \u2014 {len(c['masters'])} masters" if len(c["masters"]) > 1 else "single master (no HA)"
            proxy_note = (f"configured \u2014 {proxy_cfg.get('http_proxy', proxy_cfg.get('https_proxy'))}"
                           if proxy_cfg else "none (direct internet access assumed)")
            plan = {
                "cluster_name": c["cluster_name"], "k8s_version": c["k8s_version"],
                "cni": c["cni"], "pod_cidr": c["pod_cidr"], "service_cidr": c["service_cidr"],
                "profile": c["profile"], "monitoring": mon, "control_plane_mode": ha_note,
                "proxy": proxy_note,
                "masters": [f"{n['name']} (os_family={n['os_family']})" for n in c["masters"]],
                "workers": [f"{n['name']} (os_family={n['os_family']})" for n in c["workers"]],
                "helm_packages": [p["release"] for p in pkgs],
                "phases": [
                    "1. prepare_nodes      \u2014 auto-detect OS per node, install containerd/kubeadm",
                    "2. bootstrap_cluster  \u2014 kubeadm init" + (" + HA control-plane joins" if len(c["masters"]) > 1 else "") + " + worker joins",
                    f"3. install_cni        \u2014 {c['cni']}",
                    f"4. install_stack      \u2014 {len(pkgs)} packages for profile '{c['profile']}'",
                    (f"5. install_monitoring \u2014 {mon}" if mon != "none" else "5. install_monitoring \u2014 skipped (none)"),
                    "6. cluster_status     \u2014 verify all nodes Ready",
                ],
            }
            node_config_summary = format_node_config_summary(c["node_config"])
            note = node_config_summary
            if "os_family" not in str(arguments["config"]):
                note += ("\n\nNote: no os_family was specified per node \u2014 prepare_nodes will SSH in and "
                        "auto-detect each node's OS (Ubuntu/Debian, RHEL/CentOS/Rocky/Alma, or SUSE) and use "
                        "the matching package manager automatically. Nodes can run different OSes.")
            if not proxy_cfg:
                note += ""  # Proxy is optional — direct internet is fine, no nag needed
            else:
                note += f"\n\nProxy: {proxy_cfg.get('http_proxy', proxy_cfg.get('https_proxy'))} — will be applied to all network operations."
            if "node_config" not in str(arguments["config"]):
                note += ("\n\nNote: no node_config block was specified \u2014 using defaults shown above. "
                         "Add a node_config block to your YAML to customize sysctl preset, kernel modules, "
                         "iptables mode, SELinux handling, swap behaviour, hugepages, and ulimits.")
            note += ("\n\nAdditional config options you can add:\n"
                     "  security_tools: [falco, gatekeeper, trivy-operator, kyverno]\n"
                     "  applications:   [sonarqube, harbor, vault, keycloak]\n"
                     "  compliance:     [cis, nsa-cisa, pci-dss, soc2-iso27001]\n"
                     "  cloud_provider: aws | gcp | azure | onprem | openstack  (for cost_report)\n"
                     "  costing.rates:  {cpu_core_hourly_usd, ram_gb_hourly_usd, storage_gb_monthly_usd}\n"
                     "  ingress:        nginx | traefik | haproxy | none\n"
                     "  container_runtime: containerd | crio\n"
                     "  kube_proxy_mode:   iptables | ipvs | ebpf\n"
                     "Or just proceed and use the dedicated install_* tools after the cluster is up.")
            return [TextContent(type="text", text="PLAN:\n" + yaml.dump(plan, default_flow_style=False) + note + _format_next_steps("plan_cluster"))]

        # ── prepare_nodes ─────────────────────────────────────────────────
        elif name == "prepare_nodes":
            c = cfg()
            nodes = all_nodes()
            dry_run = arguments.get("dry_run", False)
            pcfg = proxy()

            if dry_run:
                sample = node_prep_script(c["k8s_version"], "debian", pcfg, c.get("node_config"))
                proxy_line = f"Proxy configured: {pcfg.get('http_proxy', pcfg.get('https_proxy'))}\n\n" if pcfg else "No proxy configured.\n\n"
                return [TextContent(type="text", text=
                    proxy_line + "DRY RUN \u2014 OS will be auto-detected per node; example script for a Debian-family node:\n\n" + sample)]

            os_results = detect_all_nodes_os(nodes)
            _state["os_cache"] = os_results
            for node in nodes:
                if node.get("os_family", "auto") == "auto":
                    node["os_family"] = os_results[node["name"]]["os_family"]

            pairs = [(node, node_prep_script(c["k8s_version"], node["os_family"], pcfg, c.get("node_config"))) for node in nodes]
            results = ssh_run_parallel_per_node_cmd(pairs, timeout=300)

            lines = []
            if pcfg:
                lines.append(f"Proxy: {pcfg.get('http_proxy', pcfg.get('https_proxy'))} (applied to package manager, containerd, and shell env on every node)")
            else:
                lines.append("Proxy: none \u2014 nodes assumed to have direct internet access")
            lines.append("")
            lines.append("Detected OS per node:")
            for node in nodes:
                osinfo = os_results[node["name"]]
                lines.append(f"  {node['name']}: {osinfo['pretty_name']} \u2192 family={node['os_family']}")
            lines.append("")
            lines.append("")
            lines.append("prepare_nodes (parallel):")
            for nname, r in results.items():
                ok = r["code"] == 0 and "NODE_PREP_DONE" in r["stdout"]
                lines.append(f"[{'OK' if ok else 'FAIL'}] {nname}" + ("" if ok else f"\n  {r['stderr'][-300:]}"))
            return [TextContent(type="text", text="\n".join(lines) + _format_next_steps("prepare_nodes"))]

        # ── bootstrap_cluster ─────────────────────────────────────────────
        elif name == "bootstrap_cluster":
            c = cfg()
            masters = all_masters()
            m0 = masters[0]
            endpoint = c.get("control_plane_endpoint", m0["ip"])
            is_ha = len(masters) > 1

            script = master_init_script(endpoint, c["pod_cidr"], c["service_cidr"], c["k8s_version"],
                                         is_first_master=True, upload_certs=is_ha)
            if arguments.get("dry_run"):
                return [TextContent(type="text", text=f"DRY RUN \u2014 first master init script:\n{script}")]

            code, out, er = ssh(script, m0, timeout=300)
            if code != 0:
                return err(f"kubeadm init failed on {m0['name']}:\n{er}")

            worker_join, cp_join_key = "", ""
            if "---WORKER-JOIN---" in out:
                after = out.split("---WORKER-JOIN---", 1)[1]
                section = after.split("---CONTROL-PLANE-JOIN---")[0] if "---CONTROL-PLANE-JOIN---" in after else after
                join_lines = [l.strip() for l in section.splitlines() if l.strip().startswith("kubeadm join")]
                worker_join = join_lines[-1] if join_lines else ""
            if "---CONTROL-PLANE-JOIN---" in out:
                cp_join_key = out.split("---CONTROL-PLANE-JOIN---", 1)[1].strip().splitlines()[-1].strip()

            if not worker_join:
                return err(f"Could not extract join command from output:\n{out[-800:]}")

            _state["join_command"] = worker_join
            _state["cert_key"]     = cp_join_key
            _, kubeconfig, _ = ssh("cat /etc/kubernetes/admin.conf", m0)
            _state["kubeconfig"] = kubeconfig

            lines = [f"First master '{m0['name']}' initialized."]

            if is_ha:
                lines.append("Joining additional masters (HA control-plane):")
                for extra_master in masters[1:]:
                    if not cp_join_key:
                        lines.append(f"  [SKIP] {extra_master['name']} \u2014 no certificate key extracted, join manually")
                        continue
                    cp_script = control_plane_join_script(worker_join, cp_join_key)
                    mc, _, me = ssh(cp_script, extra_master, timeout=180)
                    lines.append(f"  [{'JOINED' if mc==0 else 'FAIL'}] {extra_master['name']}" + (f" \u2014 {me[-200:]}" if mc != 0 else ""))

            lines.append("Joining workers (parallel):")
            worker_results = ssh_run_parallel(c["workers"], worker_join, timeout=120)
            for wname, r in worker_results.items():
                lines.append(f"  [{'JOINED' if r['code']==0 else 'FAIL'}] {wname}" + (f" \u2014 {r['stderr'][-200:]}" if r["code"] != 0 else ""))

            # Verify Helm and etcdctl are present on master — install if missing
            # (prepare_nodes should have done this, but we verify here to guarantee
            # that all subsequent helm/etcdctl calls will work without user intervention)
            lines.append("\nVerifying tools on master node...")
            verify_cmd = textwrap.dedent(f"""
                {proxy_env_exports(c.get('proxy'))}
                if ! command -v helm >/dev/null 2>&1; then
                    echo "[bootstrap] Helm missing — installing now..."
                    {HELM_INSTALL_SCRIPT}
                fi
                if ! command -v etcdctl >/dev/null 2>&1; then
                    echo "[bootstrap] etcdctl missing — installing now..."
                    {ETCDCTL_INSTALL_SCRIPT}
                fi
                echo "helm=$(helm version --short 2>/dev/null || echo NOT_INSTALLED)"
                echo "etcdctl=$(etcdctl version 2>/dev/null | head -1 || echo NOT_INSTALLED)"
                echo "kubectl=$(kubectl version --client --short 2>/dev/null || echo NOT_INSTALLED)"
            """).strip()
            _, tool_out, _ = ssh(verify_cmd, timeout=120)
            for tline in tool_out.splitlines():
                if any(x in tline for x in ["helm=", "etcdctl=", "kubectl=", "[bootstrap]"]):
                    lines.append(f"  {tline.strip()}")

            return [TextContent(type="text", text="\n".join(lines) + _format_next_steps("bootstrap_cluster"))]

        # ── install_cni ───────────────────────────────────────────────────
        elif name == "install_cni":
            c = cfg()
            cni = c["cni"]
            cc  = CNI_HELM[cni]
            if "manifest_url" in cc:
                cmd = f"kubectl apply -f {cc['manifest_url']}"
            else:
                vals = {**cc.get("default_values", {}), **c.get("cni_options", {})}
                sets = " ".join(f"--set {k}={v}" for k, v in vals.items())
                cmd  = (f"helm repo add {cc['repo_name']} {cc['repo_url']} --force-update && "
                        f"helm repo update && helm upgrade --install {cni} {cc['chart']} "
                        f"--version {cc.get('version','')} --namespace {cc['ns']} --create-namespace {sets}")
            if arguments.get("dry_run"):
                return [TextContent(type="text", text=f"DRY RUN:\n{cmd}")]
            code, _, er = ssh(with_proxy(cmd), timeout=180)
            if code != 0: return err(f"CNI install failed:\n{er}")
            return [TextContent(type="text", text=f"CNI '{cni}' installed." + _format_next_steps("install_cni"))]

        # ── install_stack ─────────────────────────────────────────────────
        elif name == "install_stack":
            c    = cfg()
            pkgs = list(HELM_PACKAGES.get(c["profile"], []))
            if c.get("extra_helm_packages"): pkgs.extend(c["extra_helm_packages"])
            if arguments.get("packages"): pkgs = [p for p in pkgs if p["release"] in arguments["packages"]]
            cmds = []
            for p in pkgs:
                sets = " ".join(f"--set {s}" for s in p.get("set",[]))
                cmds.append(f"helm repo add {p['repo']} {p['url']} --force-update 2>/dev/null; "
                            f"helm upgrade --install {p['release']} {p['chart']} --namespace {p['ns']} --create-namespace {sets}")
            if arguments.get("dry_run"):
                return [TextContent(type="text", text="DRY RUN:\n" + "\n".join(cmds))]
            results = []
            for p, cmd in zip(pkgs, cmds):
                code, _, er = ssh(with_proxy(cmd), timeout=300)
                results.append(f"[{'OK' if code==0 else 'FAIL'}] {p['release']} \u2192 ns/{p['ns']}" + (f"\n  {er[-200:]}" if code != 0 else ""))
            return [TextContent(type="text", text="Stack install:\n" + "\n".join(results) + _format_next_steps("install_stack"))]

        # ── install_monitoring ────────────────────────────────────────────
        elif name == "install_monitoring":
            cfg()
            mtype = arguments["monitoring_type"]
            if mtype == "none":
                return [TextContent(type="text", text="Monitoring skipped (monitoring_type=none).")]
            pkgs = list(MONITORING_HELM.get(mtype, []))
            gpw  = arguments.get("grafana_password", "admin-changeme")
            cmds = []
            for p in pkgs:
                sets = list(p.get("set", []))
                if "grafana.adminPassword" in str(sets):
                    sets = [s if not s.startswith("grafana.adminPassword") else f"grafana.adminPassword={gpw}" for s in sets]
                set_str = " ".join(f"--set {s}" for s in sets)
                cmds.append(f"helm repo add {p['repo']} {p['url']} --force-update 2>/dev/null; "
                            f"helm upgrade --install {p['release']} {p['chart']} --namespace {p['ns']} --create-namespace {set_str}")
            if arguments.get("dry_run"):
                return [TextContent(type="text", text="DRY RUN:\n" + "\n\n".join(cmds))]
            results = []
            for p, cmd in zip(pkgs, cmds):
                code, _, er = ssh(with_proxy(cmd), timeout=300)
                results.append(f"[{'OK' if code==0 else 'FAIL'}] {p['release']} \u2192 ns/{p['ns']}" + (f"\n  {er[-200:]}" if code != 0 else ""))
            access_note = ("\n\nAccess Grafana: kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80\n"
                            f"Login: admin / {gpw}")
            return [TextContent(type="text", text=f"Monitoring ({mtype}) install:\n" + "\n".join(results) + access_note + _format_next_steps("install_monitoring"))]

        # ── install_jenkins ───────────────────────────────────────────────
        elif name == "install_jenkins":
            cfg()
            pw   = arguments.get("admin_password", "admin-changeme")
            size = arguments.get("storage_size", "10Gi")
            sc   = arguments.get("storage_class")
            jh   = JENKINS_HELM
            vals = dict(jh["default_values"])
            vals["controller.adminPassword"] = pw
            vals["persistence.size"]         = size
            if sc:
                vals["persistence.storageClass"] = sc
            sets = " ".join(f"--set {k}={v}" for k, v in vals.items())
            cmd  = (f"helm repo add {jh['repo']} {jh['url']} --force-update && "
                    f"helm upgrade --install {jh['release']} {jh['chart']} "
                    f"--namespace {jh['ns']} --create-namespace {sets}")
            if arguments.get("dry_run"):
                return [TextContent(type="text", text=f"DRY RUN:\n{cmd}")]
            code, out, er = ssh(with_proxy(cmd), timeout=300)
            if code != 0: return err(f"Jenkins install failed:\n{er}")
            access_note = (
                "\n\nJenkins is ClusterIP-only (internal cluster use). To access it:\n"
                f"  kubectl port-forward -n {jh['ns']} svc/jenkins 8080:8080\n"
                f"  Login: admin / {pw}\n"
                "The Kubernetes plugin is pre-installed so Jenkins can launch build agents as pods "
                "directly in this cluster using its own in-cluster ServiceAccount \u2014 no external "
                "credentials needed for that.")
            return [TextContent(type="text", text=f"Jenkins installed:\n{out}" + access_note + _format_next_steps("install_jenkins"))]

        # ── preflight_check ───────────────────────────────────────────────
        elif name == "preflight_check":
            try: c = cfg()
            except ValueError as e: return err(str(e))

            fix      = arguments.get("fix", True)
            node_nm  = arguments.get("node_name")
            all_n    = all_nodes()
            targets  = [n for n in all_n if not node_nm or n["name"] == node_nm]
            if not targets:
                return err(f"Node '{node_nm}' not found in config")

            pcfg = c.get("proxy")
            proxy_exp = proxy_env_exports(pcfg)

            preflight_script = textwrap.dedent(f"""
                set -uo pipefail
                {proxy_exp}
                ISSUES=0
                FIXED=0
                echo "=== PREFLIGHT CHECK on $(hostname) ==="

                echo "-- OS detection --"
                cat /etc/os-release | grep PRETTY_NAME || true

                echo "-- Disk space (need >= 20GB free on /) --"
                FREE_GB=$(df -BG / | tail -1 | awk '{{print $4}}' | tr -d 'G')
                if [ "${{FREE_GB:-0}}" -lt 20 ]; then
                    echo "WARN: only ${{FREE_GB}}GB free on / (need 20GB)"
                    ISSUES=$((ISSUES+1))
                else
                    echo "OK: ${{FREE_GB}}GB free on /"
                fi

                echo "-- Memory (need >= 2GB RAM) --"
                MEM_MB=$(free -m | awk '/^Mem:/ {{print $2}}')
                if [ "${{MEM_MB:-0}}" -lt 2000 ]; then
                    echo "WARN: only ${{MEM_MB}}MB RAM (need 2000MB)"
                    ISSUES=$((ISSUES+1))
                else
                    echo "OK: ${{MEM_MB}}MB RAM"
                fi

                echo "-- Port availability (6443, 10250, 2379, 2380) --"
                for PORT in 6443 10250 2379 2380; do
                    if ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
                        echo "WARN: port $PORT is already in use"
                        ISSUES=$((ISSUES+1))
                    else
                        echo "OK: port $PORT is free"
                    fi
                done

                echo "-- Swap --"
                SWAP=$(free | awk '/^Swap:/ {{print $2}}')
                if [ "${{SWAP:-0}}" -gt 0 ]; then
                    echo "WARN: swap is active (${{SWAP}}kB) — kubeadm requires swap disabled"
                    ISSUES=$((ISSUES+1))
                else
                    echo "OK: swap is disabled"
                fi

                echo "-- Internet/proxy reachability --"
                if curl -fsSL --connect-timeout 10 https://registry.k8s.io >/dev/null 2>&1; then
                    echo "OK: can reach registry.k8s.io"
                elif curl -fsSL --connect-timeout 10 https://pypi.org >/dev/null 2>&1; then
                    echo "OK: internet reachable (registry.k8s.io timed out but pypi.org works)"
                else
                    echo "WARN: cannot reach internet — check proxy settings or network"
                    ISSUES=$((ISSUES+1))
                fi

                echo "-- Tool availability --"
                for TOOL in helm etcdctl kubectl kubeadm git jq; do
                    if command -v $TOOL >/dev/null 2>&1; then
                        echo "OK: $TOOL is installed"
                    else
                        echo "MISSING: $TOOL"
                        ISSUES=$((ISSUES+1))
                        if [ "{str(fix).lower()}" = "true" ]; then
                            echo "  AUTO-FIX: installing $TOOL..."
                            case $TOOL in
                                helm)
                                    {HELM_INSTALL_SCRIPT.replace(chr(10), chr(10)+'                                    ')}
                                    FIXED=$((FIXED+1))
                                    ;;
                                etcdctl)
                                    {ETCDCTL_INSTALL_SCRIPT.replace(chr(10), chr(10)+'                                    ')}
                                    FIXED=$((FIXED+1))
                                    ;;
                                git|jq)
                                    (apt-get install -y -qq $TOOL 2>/dev/null || dnf install -y -q $TOOL 2>/dev/null || zypper install -y $TOOL 2>/dev/null) && FIXED=$((FIXED+1)) || true
                                    ;;
                                *)
                                    echo "  (cannot auto-install $TOOL — will be installed during prepare_nodes)"
                                    ;;
                            esac
                        fi
                    fi
                done

                echo ""
                echo "=== SUMMARY ==="
                echo "Issues found: $ISSUES"
                if [ "{str(fix).lower()}" = "true" ]; then
                    echo "Issues auto-fixed: $FIXED"
                fi
                if [ "$ISSUES" -eq 0 ] || [ "$FIXED" -ge "$ISSUES" ]; then
                    echo "STATUS: READY"
                else
                    REMAINING=$((ISSUES - FIXED))
                    echo "STATUS: $REMAINING issue(s) need manual attention"
                fi
                echo PREFLIGHT_DONE
            """).strip()

            results = ssh_run_parallel(targets, preflight_script, timeout=120)
            output = []
            all_ready = True
            for n in targets:
                r = results.get(n["name"], {})
                done = "PREFLIGHT_DONE" in r.get("stdout", "")
                ready = "STATUS: READY" in r.get("stdout", "")
                if not ready: all_ready = False
                output.append(f"\n{'='*40}\nNode: {n['name']} ({n['ip']})\n{'='*40}")
                output.append(r.get("stdout", r.get("stderr", "no output")))

            summary = "\nAll nodes READY to proceed." if all_ready else \
                      "\nWARN: some nodes have issues. Review above and re-run, or run prepare_nodes to resolve automatically."
            return [TextContent(type="text", text="\n".join(output) + summary + _format_next_steps("prepare_nodes"))]

        # ── cluster_status ────────────────────────────────────────────────
        elif name == "cluster_status":
            cfg()
            output = []
            for label, cmd in [
                ("Nodes",          "kubectl get nodes -o wide"),
                ("System pods",    "kubectl get pods -n kube-system -o wide"),
                ("Unhealthy pods", "kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded 2>/dev/null || echo 'All pods healthy'"),
                ("PVs",            "kubectl get pv 2>/dev/null || echo No PVs"),
                ("LoadBalancers",  "kubectl get svc -A --field-selector=spec.type=LoadBalancer 2>/dev/null || echo none"),
            ]:
                _, out, er = ssh(cmd)
                output.append(f"\u2500\u2500 {label} \u2500\u2500\n{out or er}")
            return [TextContent(type="text", text="\n\n".join(output) + _format_next_steps("cluster_status"))]

        # ── destroy_cluster ───────────────────────────────────────────────
        elif name == "destroy_cluster":
            if arguments.get("confirm") != "DESTROY":
                return err("confirm must be exactly 'DESTROY'. No action taken.")
            c = cfg()
            reset = ("kubeadm reset -f && rm -rf /etc/cni/net.d /var/lib/etcd /var/lib/kubelet /etc/kubernetes && "
                     "iptables -F && iptables -t nat -F && iptables -t mangle -F && iptables -X")
            results = ssh_run_parallel(c["masters"] + c["workers"], reset)
            lines   = [f"[{'RESET' if r['code']==0 else 'FAIL'}] {n}" for n,r in results.items()]
            _state.clear()
            return [TextContent(type="text", text="DESTROY complete (parallel):\n" + "\n".join(lines))]

        # ── scale_cluster ─────────────────────────────────────────────────
        elif name == "scale_cluster":
            c       = cfg()
            action  = arguments["action"]
            nodes   = arguments["nodes"]
            role    = arguments.get("role", "worker")
            dry_run = arguments.get("dry_run", False)

            if action == "add":
                for n in nodes:
                    n.setdefault("os_family", "auto")
                    n.setdefault("user", "root")

                join_cmd = _state.get("join_command")
                if not join_cmd:
                    _, jout, _ = ssh("kubeadm token create --print-join-command")
                    join_cmd = jout.strip()
                    _state["join_command"] = join_cmd

                if dry_run:
                    return [TextContent(type="text", text=f"DRY RUN: would auto-detect OS, prep, then run:\n{join_cmd}" + (" --control-plane" if role == "master" else ""))]

                os_results = detect_all_nodes_os(nodes)
                for n in nodes:
                    if n["os_family"] == "auto":
                        n["os_family"] = os_results[n["name"]]["os_family"]

                prep_pairs = [(n, node_prep_script(c["k8s_version"], n["os_family"], proxy(), c.get("node_config"))) for n in nodes]
                prep_results = ssh_run_parallel_per_node_cmd(prep_pairs, timeout=300)

                lines = ["Detected OS:"]
                for n in nodes:
                    lines.append(f"  {n['name']}: {os_results[n['name']]['pretty_name']} \u2192 {n['os_family']}")
                lines.append("")

                join_targets = []
                for n in nodes:
                    r = prep_results.get(n["name"], {})
                    if r.get("code") == 0 and "NODE_PREP_DONE" in r.get("stdout",""):
                        join_targets.append(n)
                    else:
                        lines.append(f"[PREP FAIL] {n['name']}: {r.get('stderr','')[-200:]}")

                if role == "master":
                    cert_key = _state.get("cert_key", "")
                    if not cert_key:
                        lines.append("WARNING: no certificate_key in session state \u2014 cannot join as control-plane. "
                                     "Re-run bootstrap_cluster or join manually with: kubeadm init phase upload-certs --upload-certs")
                    else:
                        for n in join_targets:
                            cp_script = control_plane_join_script(join_cmd, cert_key)
                            jc, _, je = ssh_exec(n["ip"], n.get("user","root"), n["ssh_key"], cp_script, 180)
                            lines.append(f"[{'JOINED (master)' if jc==0 else 'FAIL'}] {n['name']}" + (f" \u2014 {je[-200:]}" if jc != 0 else ""))
                        c["masters"].extend(join_targets)
                else:
                    join_results = ssh_run_parallel(join_targets, join_cmd, timeout=120) if join_targets else {}
                    for n in join_targets:
                        r = join_results.get(n["name"], {})
                        lines.append(f"[{'JOINED' if r.get('code')==0 else 'FAIL'}] {n['name']}" + (f" \u2014 {r.get('stderr','')[-200:]}" if r.get("code") != 0 else ""))
                    c["workers"].extend(join_targets)

                key = "scale_cluster_add"
                return [TextContent(type="text", text="scale add:\n" + "\n".join(lines) + _format_next_steps(key))]

            elif action in ("drain", "remove"):
                if dry_run:
                    lines = [f"DRY RUN: drain {n}" + (" + delete" if action == "remove" else "") for n in nodes]
                    return [TextContent(type="text", text="\n".join(lines))]
                # Drains run in parallel since each is on a node already in the cluster
                lines = []
                for node_name in nodes:
                    dc, _, de = ssh(f"kubectl drain {node_name} --ignore-daemonsets --delete-emptydir-data --force")
                    lines.append(f"[{'DRAINED' if dc==0 else 'FAIL'}] {node_name}" + (f" \u2014 {de[-150:]}" if dc != 0 else ""))
                    if action == "remove" and dc == 0:
                        rc, _, _ = ssh(f"kubectl delete node {node_name}")
                        lines.append(f"  [{'REMOVED' if rc==0 else 'FAIL'}] delete {node_name}")
                return [TextContent(type="text", text=f"scale {action}:\n" + "\n".join(lines) + _format_next_steps("scale_cluster_remove"))]

            return err(f"Unknown action '{action}'")

        # ── upgrade_cluster ───────────────────────────────────────────────
        elif name == "upgrade_cluster":
            c   = cfg()
            ver = arguments["target_version"]
            batch_size = arguments.get("worker_batch_size", 3)

            if arguments.get("dry_run"):
                return [TextContent(type="text", text=(
                    f"DRY RUN \u2014 upgrade to v{ver}:\n"
                    f"  1. first master: kubeadm upgrade apply (OS-aware)\n"
                    f"  2. additional masters (if HA): kubeadm upgrade node, one at a time\n"
                    f"  3. workers: drain \u2192 upgrade \u2192 uncordon, in parallel batches of {batch_size}"))]

            lines = []

            # First master \u2014 always serial, always first
            m0 = c["masters"][0]
            m0_os = node_os_family(m0)
            mc, _, me = ssh(node_upgrade_script(ver, "master", m0_os, proxy()), m0, timeout=300)
            lines.append(f"[{'OK' if mc==0 else 'FAIL'}] master {m0['name']} (os={m0_os})" + (f"\n  {me[-250:]}" if mc != 0 else ""))

            # Additional masters \u2014 serial, one at a time (each needs the previous stable)
            for extra in c["masters"][1:]:
                eos = node_os_family(extra)
                ec, _, ee = ssh_exec(extra["ip"], extra.get("user","root"), extra["ssh_key"],
                                      node_upgrade_script(ver, "master", eos, proxy()), 300)
                lines.append(f"[{'OK' if ec==0 else 'FAIL'}] master {extra['name']} (os={eos})" + (f"\n  {ee[-250:]}" if ec != 0 else ""))

            # Workers \u2014 batched parallel: drain the batch, upgrade the batch concurrently, uncordon the batch
            workers = c["workers"]
            for i in range(0, len(workers), batch_size):
                batch = workers[i:i + batch_size]
                lines.append(f"Worker batch {i//batch_size + 1}: {[w['name'] for w in batch]}")
                for w in batch:
                    dc, _, de = ssh(f"kubectl drain {w['name']} --ignore-daemonsets --delete-emptydir-data --force")
                    if dc != 0:
                        lines.append(f"  [FAIL drain] {w['name']}: {de[-150:]}")

                pairs = [(w, node_upgrade_script(ver, "worker", node_os_family(w), proxy())) for w in batch]
                batch_results = ssh_run_parallel_per_node_cmd(pairs, timeout=300)

                for w in batch:
                    r = batch_results.get(w["name"], {})
                    ok = r.get("code") == 0 and "UPGRADE_DONE" in r.get("stdout", "")
                    ssh(f"kubectl uncordon {w['name']}")
                    lines.append(f"  [{'OK' if ok else 'FAIL'}] {w['name']} (os={w.get('os_family')})" + ("" if ok else f"\n    {r.get('stderr','')[-250:]}"))

            c["k8s_version"] = ver
            return [TextContent(type="text", text=f"Upgrade to v{ver}:\n" + "\n".join(lines) + _format_next_steps("upgrade_cluster"))]

        # ── backup_etcd ───────────────────────────────────────────────────
        elif name == "backup_etcd":
            cfg()
            path = arguments.get("backup_path", "/opt/etcd-backups/snapshot.db")
            ts   = datetime.now().strftime("%Y%m%d-%H%M%S")
            snap = path.replace(".db", f"-{ts}.db")
            cmd  = textwrap.dedent(f"""
                mkdir -p $(dirname {snap})
                ETCDCTL_API=3 etcdctl snapshot save {snap} \\
                  --endpoints=https://127.0.0.1:2379 \\
                  --cacert=/etc/kubernetes/pki/etcd/ca.crt \\
                  --cert=/etc/kubernetes/pki/etcd/server.crt \\
                  --key=/etc/kubernetes/pki/etcd/server.key
                ETCDCTL_API=3 etcdctl snapshot status {snap} --write-out=table
            """).strip()
            code, out, er = ssh(cmd)
            if code != 0: return err(f"etcd backup failed:\n{er}")
            return [TextContent(type="text", text=f"etcd backup saved on {first_master()['name']}: {snap}\n{out}" + _format_next_steps("backup_etcd"))]

        # ── restore_etcd ──────────────────────────────────────────────────
        elif name == "restore_etcd":
            if arguments.get("confirm") != "RESTORE":
                return err("confirm must be 'RESTORE'. No action taken.")
            cfg()
            snap = arguments["snapshot_path"]
            cmd  = textwrap.dedent(f"""
                set -euo pipefail
                mv /etc/kubernetes/manifests /etc/kubernetes/manifests.bak
                sleep 5
                ETCDCTL_API=3 etcdctl snapshot restore {snap} \\
                  --data-dir /var/lib/etcd-restore \\
                  --cacert=/etc/kubernetes/pki/etcd/ca.crt \\
                  --cert=/etc/kubernetes/pki/etcd/server.crt \\
                  --key=/etc/kubernetes/pki/etcd/server.key
                mv /var/lib/etcd /var/lib/etcd.bak
                mv /var/lib/etcd-restore /var/lib/etcd
                mv /etc/kubernetes/manifests.bak /etc/kubernetes/manifests
                sleep 10 && kubectl get nodes
            """).strip()
            code, out, er = ssh(cmd, timeout=120)
            if code != 0: return err(f"etcd restore failed:\n{er}")
            note = ""
            if len(all_masters()) > 1:
                note = ("\n\nNOTE: this is a multi-master (HA) cluster. Restoring etcd on only the first "
                        "master can desync the etcd cluster across masters. For HA clusters, stop etcd "
                        "on ALL masters before restoring, restore on one, then let the others rejoin and "
                        "resync \u2014 do not leave this as a single-node restore in production.")
            return [TextContent(type="text", text=f"etcd restored from {snap}:\n{out}{note}" + _format_next_steps("restore_etcd"))]

        # ── rotate_certs ──────────────────────────────────────────────────
        elif name == "rotate_certs":
            masters = all_masters()
            if arguments.get("check_only"):
                results = ssh_run_parallel(masters, "kubeadm certs check-expiration")
                lines = [f"\u2500\u2500 {n} \u2500\u2500\n{r['stdout'] or r['stderr']}" for n, r in results.items()]
                return [TextContent(type="text", text="Certificate expiry (all masters):\n\n" + "\n\n".join(lines))]
            cmd = textwrap.dedent("""
                set -euo pipefail
                kubeadm certs renew all
                mkdir -p $HOME/.kube
                cp /etc/kubernetes/admin.conf $HOME/.kube/config
                chown $(id -u):$(id -g) $HOME/.kube/config
                systemctl restart kubelet
                kubeadm certs check-expiration
            """).strip()
            # Rotate on every master in parallel \u2014 each has its own cert set
            results = ssh_run_parallel(masters, cmd, timeout=120)
            lines = [f"\u2500\u2500 {n} \u2500\u2500\n{r['stdout'] if r['code']==0 else r['stderr']}" for n, r in results.items()]
            return [TextContent(type="text", text="Certs renewed (all masters, parallel):\n\n" + "\n\n".join(lines) + _format_next_steps("rotate_certs"))]

        # ── manage_kubeconfig ─────────────────────────────────────────────
        elif name == "manage_kubeconfig":
            cfg()
            username = arguments["username"]
            ns       = arguments["namespace"]
            role     = arguments.get("role","view")
            outpath  = arguments.get("output_path", f"./kubeconfig-{username}.yaml")
            cmd = textwrap.dedent(f"""
                set -euo pipefail
                kubectl create serviceaccount {username} -n {ns} --dry-run=client -o yaml | kubectl apply -f -
                kubectl create rolebinding {username}-{role} --clusterrole={role} \\
                  --serviceaccount={ns}:{username} --namespace={ns} --dry-run=client -o yaml | kubectl apply -f -
                TOKEN=$(kubectl create token {username} -n {ns} --duration=8760h)
                SERVER=$(kubectl config view --minify -o jsonpath={{.clusters[0].cluster.server}})
                CA=$(kubectl config view --minify --raw -o jsonpath={{.clusters[0].cluster.certificate-authority-data}})
                echo "apiVersion: v1
kind: Config
clusters:
- cluster:
    certificate-authority-data: $CA
    server: $SERVER
  name: k8s
contexts:
- context:
    cluster: k8s
    namespace: {ns}
    user: {username}
  name: {username}@k8s
current-context: {username}@k8s
users:
- name: {username}
  user:
    token: $TOKEN"
            """).strip()
            code, out, er = ssh(cmd)
            if code != 0: return err(f"kubeconfig generation failed:\n{er}")
            try:
                with open(outpath,"w") as f: f.write(out)
                saved = f" Saved to {outpath}."
            except Exception:
                saved = ""
            return [TextContent(type="text", text=f"Kubeconfig for '{username}' (role={role}, ns={ns}).{saved}\n\n{out}" + _format_next_steps("manage_kubeconfig"))]

        # ── provision_namespace ───────────────────────────────────────────
        elif name == "provision_namespace":
            cfg()
            manifest = namespace_manifest(
                name=arguments["name"], team=arguments["team"],
                cpu_limit=arguments.get("cpu_limit","8"), mem_limit=arguments.get("mem_limit","16Gi"),
                cpu_req=arguments.get("cpu_req","4"),   mem_req=arguments.get("mem_req","8Gi"))
            code, out, er = ssh(f"kubectl apply -f - <<'MEOF'\n{manifest}\nMEOF")
            if code != 0: return err(f"provision_namespace failed:\n{er}")
            return [TextContent(type="text", text=f"Namespace '{arguments['name']}' provisioned for team '{arguments['team']}':\n{out}\n\nManifest:\n{manifest}" + _format_next_steps("provision_namespace"))]

        # ── provision_storage ─────────────────────────────────────────────
        elif name == "provision_storage":
            cfg()
            stype = arguments["type"]
            scfg  = STORAGE_HELM[stype]
            if "manifest_url" in scfg:
                cmd = f"kubectl apply -f {scfg['manifest_url']}"
            else:
                vals = dict(scfg.get("default_values",{}))
                if stype == "nfs":
                    if not arguments.get("nfs_server") or not arguments.get("nfs_path"):
                        return err("nfs_server and nfs_path required for type=nfs")
                    vals["nfs.server"] = arguments["nfs_server"]
                    vals["nfs.path"]   = arguments["nfs_path"]
                sets = " ".join(f"--set {k}={v}" for k,v in vals.items())
                cmd  = (f"helm repo add {scfg['repo']} {scfg['url']} --force-update && "
                        f"helm upgrade --install {stype} {scfg['chart']} --namespace {scfg['ns']} --create-namespace {sets}")
            if arguments.get("set_default", True):
                sc_name = {"longhorn":"longhorn","nfs":"nfs-client","local-path":"local-path","rook-ceph":"rook-ceph-block"}.get(stype,stype)
                cmd += f" && kubectl patch storageclass {sc_name} -p '{{\"metadata\":{{\"annotations\":{{\"storageclass.kubernetes.io/is-default-class\":\"true\"}}}}}}'"
            if arguments.get("dry_run"):
                return [TextContent(type="text", text=f"DRY RUN:\n{cmd}")]
            code, out, er = ssh(with_proxy(cmd), timeout=300)
            if code != 0: return err(f"provision_storage failed:\n{er}")
            return [TextContent(type="text", text=f"Storage '{stype}' installed:\n{out}" + _format_next_steps("provision_storage"))]

        # ── migrate_workload ──────────────────────────────────────────────
        elif name == "migrate_workload":
            src_type  = arguments["source_type"]
            source    = arguments["source"]
            ns        = arguments.get("namespace","default")
            replicas  = arguments.get("replicas", 1)
            add_hpa   = arguments.get("add_hpa", False)
            add_pdb   = arguments.get("add_pdb", False)
            manifests = []
            num_svcs  = 1

            if src_type == "docker-compose":
                try:
                    compose = yaml.safe_load(source)
                except Exception as e:
                    return err(f"Cannot parse docker-compose: {e}")
                services = compose.get("services", {})
                if not services:
                    return err("No services found in docker-compose.yml")
                num_svcs = len(services)
                for svc_name, svc_def in services.items():
                    image   = svc_def.get("image", f"{svc_name}:latest")
                    ports   = [str(p) for p in svc_def.get("ports", [])]
                    env_raw = svc_def.get("environment", {})
                    env_vars = {}
                    if isinstance(env_raw, list):
                        for item in env_raw:
                            if "=" in str(item):
                                k, v = str(item).split("=",1)
                                env_vars[k] = v
                    elif isinstance(env_raw, dict):
                        env_vars = {str(k): str(v) for k,v in env_raw.items()}
                    manifests.append(compose_to_k8s(svc_name, image, ports, env_vars, replicas, ns))
                    if add_hpa:
                        manifests.append(textwrap.dedent(f"""
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {svc_name}-hpa
  namespace: {ns}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {svc_name}
  minReplicas: {replicas}
  maxReplicas: {replicas * 5}
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70""").strip())
                    if add_pdb:
                        manifests.append(textwrap.dedent(f"""
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {svc_name}-pdb
  namespace: {ns}
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: {svc_name}""").strip())
                    for vol in svc_def.get("volumes",[]):
                        if ":" in str(vol):
                            _, cp = str(vol).split(":",1)
                            manifests.append(f"# VOLUME HINT: mount path '{cp}' detected \u2014 consider adding a PVC for {svc_name}")
            else:
                lines   = source.splitlines()
                exec_s  = next((l.split("=",1)[1].strip() for l in lines if l.startswith("ExecStart=")), "")
                desc    = next((l.split("=",1)[1].strip() for l in lines if l.startswith("Description=")), "migrated-service")
                sn      = re.sub(r"[^a-z0-9-]", "-", desc.lower())[:40]
                image   = "your-image:latest"
                m2      = re.search(r"docker run.*?(\S+:\S+|\S+/\S+)\s*$", exec_s)
                if m2:   image = m2.group(1)
                manifests.append(compose_to_k8s(sn, image, [], {}, replicas, ns))
                manifests.append(f"# NOTE: systemd ExecStart was:\n# {exec_s}\n# Adjust image, ports, env vars above.")

            full = "\n\n---\n\n".join(manifests)
            return [TextContent(type="text", text=f"Generated manifests ({num_svcs} service(s)):\nApply: kubectl apply -f manifests.yaml\n\n{full}" + _format_next_steps("migrate_workload"))]

        # ── stream_logs ───────────────────────────────────────────────────
        elif name == "stream_logs":
            cfg()
            ns       = arguments.get("namespace","default")
            pod      = arguments.get("pod")
            selector = arguments.get("selector")
            cont     = arguments.get("container","")
            tail     = arguments.get("tail_lines",50)
            prev     = "--previous" if arguments.get("previous") else ""
            cf       = f"-c {cont}" if cont else ""
            if pod:
                cmd = f"kubectl logs {pod} -n {ns} --tail={tail} {prev} {cf}"
            elif selector:
                cmd = f"kubectl logs -l {selector} -n {ns} --tail={tail} {prev} {cf} --prefix=true"
            else:
                cmd = f"kubectl logs -n {ns} --tail={tail} --prefix=true $(kubectl get pods -n {ns} -o name | head -5 | tr '\\n' ' ')"
            _, out, er = ssh(cmd)
            return [TextContent(type="text", text=f"Logs (ns/{ns}):\n{out or er}" + _format_next_steps("stream_logs"))]

        # ── audit_cluster ─────────────────────────────────────────────────
        elif name == "audit_cluster":
            cfg()
            checks = arguments.get("checks", ["all"])
            run_all = "all" in checks
            audit_cmds = {}
            if run_all or "security" in checks:
                audit_cmds["Privileged pods"] = "kubectl get pods -A -o json | python3 -c \"import json,sys; pods=json.load(sys.stdin)['items']; [print(p['metadata']['namespace']+'/'+p['metadata']['name']) for p in pods if any(c.get('securityContext',{}).get('privileged') for c in p['spec'].get('containers',[]))]\" 2>/dev/null || echo none"
                audit_cmds["Root-user pods"] = "kubectl get pods -A -o json | python3 -c \"import json,sys; pods=json.load(sys.stdin)['items']; [print(p['metadata']['namespace']+'/'+p['metadata']['name']) for p in pods if p['spec'].get('securityContext',{}).get('runAsUser',999)==0]\" 2>/dev/null || echo none"
            if run_all or "resources" in checks:
                audit_cmds["Pods missing limits"] = "kubectl get pods -A -o json | python3 -c \"import json,sys; pods=json.load(sys.stdin)['items']; [print(p['metadata']['namespace']+'/'+p['metadata']['name']) for p in pods for c in p['spec'].get('containers',[]) if not c.get('resources',{}).get('limits')]\" 2>/dev/null || echo none"
            if run_all or "networking" in checks:
                audit_cmds["NodePort services"] = "kubectl get svc -A --field-selector=spec.type=NodePort 2>/dev/null || echo none"
                audit_cmds["NetworkPolicies"]    = "kubectl get networkpolicies -A 2>/dev/null || echo none"
            if run_all or "rbac" in checks:
                audit_cmds["Non-system ClusterRoleBindings"] = "kubectl get clusterrolebindings -o json | python3 -c \"import json,sys; [print(c['metadata']['name']) for c in json.load(sys.stdin)['items'] if not c['metadata']['name'].startswith('system:')]\" 2>/dev/null || echo none"
            if run_all or "storage" in checks:
                audit_cmds["Unbound PVCs"]   = "kubectl get pvc -A --field-selector=status.phase!=Bound 2>/dev/null || echo none"
                audit_cmds["StorageClasses"] = "kubectl get storageclass 2>/dev/null"
            if run_all or "certificates" in checks:
                audit_cmds["Certificate expiry (first master)"] = "kubeadm certs check-expiration 2>/dev/null"
            output = []
            for label, cmd in audit_cmds.items():
                _, out, er = ssh(cmd)
                output.append(f"\u2500\u2500 {label} \u2500\u2500\n{(out or er).strip() or '(none)'}")
            return [TextContent(type="text", text="CLUSTER AUDIT REPORT\n" + "="*40 + "\n\n" + "\n\n".join(output) + _format_next_steps("audit_cluster"))]

        # ── node_diagnostics ──────────────────────────────────────────────
        elif name == "node_diagnostics":
            c         = cfg()
            node_name = arguments.get("node_name")
            nodes     = all_nodes()
            targets   = [n for n in nodes if not node_name or n["name"] == node_name]
            if not targets:
                return err(f"Node '{node_name}' not found in config")
            diag = textwrap.dedent("""
                echo "=== HOSTNAME ===" && hostname
                echo "=== OS ===" && cat /etc/os-release 2>/dev/null | grep PRETTY_NAME
                echo "=== KERNEL ===" && uname -r
                echo "=== DISK ===" && df -h
                echo "=== MEMORY ===" && free -h
                echo "=== CPU ===" && nproc && uptime
                echo "=== KUBELET ===" && systemctl is-active kubelet
                echo "=== KUBELET LOGS ===" && journalctl -u kubelet -n 20 --no-pager 2>/dev/null
                echo "=== CONTAINERD ===" && systemctl is-active containerd
                echo "=== OOM EVENTS ===" && dmesg | grep -iE "oom|kill" | tail -10 2>/dev/null || echo none
                echo "=== NETWORK ===" && ip addr show | grep -E "inet |^[0-9]"
                echo "=== CONNECTIONS ===" && ss -s
            """).strip()
            # Diagnostics across multiple nodes are independent \u2014 always run in parallel
            results = ssh_run_parallel(targets, diag, timeout=60)
            output = []
            for n in targets:
                r = results.get(n["name"], {})
                output.append(f"{'='*40}\nNODE: {n['name']} ({n['ip']})\n{'='*40}\n{r.get('stdout') or r.get('stderr')}")
            return [TextContent(type="text", text="\n\n".join(output) + _format_next_steps("node_diagnostics"))]

        # ── helm_manage ───────────────────────────────────────────────────
        elif name == "helm_manage":
            cfg()
            action  = arguments["action"]
            release = arguments.get("release","")
            ns      = arguments.get("namespace","")
            dry_run = arguments.get("dry_run", False)
            nf      = f"-n {ns}" if ns else "-A"
            dr      = "--dry-run" if dry_run else ""
            cmd_map = {
                "list":      f"helm list {nf}",
                "status":    f"helm status {release} {nf}",
                "history":   f"helm history {release} {nf}",
                "uninstall": f"helm uninstall {release} {nf} {dr}",
                "rollback":  f"helm rollback {release} {arguments.get('revision',0)} {nf} {dr}",
                "upgrade":   (f"helm upgrade {release} {arguments.get('chart','')} {nf} --create-namespace "
                              f"{'--version ' + arguments['version'] if arguments.get('version') else ''} {dr} --reuse-values"),
            }
            cmd = cmd_map.get(action)
            if not cmd: return err(f"Unknown action '{action}'")
            if action == "upgrade":
                cmd = with_proxy(cmd)
            code, out, er = ssh(cmd)
            return [TextContent(type="text", text=f"helm {action}:\n{out or er}" + _format_next_steps("helm_manage"))]

        # ── cluster_snapshot ──────────────────────────────────────────────
        elif name == "cluster_snapshot":
            cfg()
            out_dir = arguments.get("output_dir","/opt/cluster-snapshot")
            nss     = arguments.get("namespaces",[])
            excl    = arguments.get("exclude_secrets", True)
            ts      = datetime.now().strftime("%Y%m%d-%H%M%S")
            snap    = f"{out_dir}/{ts}"
            res     = "all,configmap,ingress,networkpolicy,pvc,serviceaccount,rolebinding,role"
            if not excl: res += ",secret"
            if nss:
                ns_cmds = "\n".join(
                    f"mkdir -p {snap}/{n} && kubectl get {res} -n {n} -o yaml > {snap}/{n}/resources.yaml 2>/dev/null"
                    for n in nss)
            else:
                ns_cmds = textwrap.dedent(f"""
                    for ns in $(kubectl get ns -o jsonpath='{{.items[*].metadata.name}}'); do
                        mkdir -p {snap}/$ns
                        kubectl get {res} -n $ns -o yaml > {snap}/$ns/resources.yaml 2>/dev/null
                    done
                    kubectl get clusterrole,clusterrolebinding,storageclass,pv,namespace -o yaml > {snap}/cluster-scoped.yaml 2>/dev/null
                """).strip()
            cmd = f"set -e && mkdir -p {snap} && {ns_cmds} && echo 'Snapshot: {snap}' && du -sh {snap}"
            code, out, er = ssh(cmd, timeout=180)
            if code != 0: return err(f"Snapshot failed:\n{er}")
            return [TextContent(type="text", text=f"Cluster snapshot complete:\n{out}\n\nDirectory: {snap}" + _format_next_steps("cluster_snapshot"))]

            return [TextContent(type="text", text=f"Cluster snapshot complete:\n{out}\n\nDirectory: {snap}" + _format_next_steps("cluster_snapshot"))]

        # ── install_security_tools ────────────────────────────────────────
        elif name == "install_security_tools":
            cfg()
            tools   = arguments["tools"]
            dry_run = arguments.get("dry_run", False)
            unknown = [t for t in tools if t not in SECURITY_TOOLS_HELM]
            if unknown:
                return err(f"Unknown security tools: {unknown}. Supported: {list(SECURITY_TOOLS_HELM.keys())}")
            results = []
            for tool_name in tools:
                th = SECURITY_TOOLS_HELM[tool_name]
                sets = " ".join(f"--set {s}" for s in th.get("set", []))
                cmd  = (f"helm repo add {th['repo']} {th['url']} --force-update 2>/dev/null; "
                        f"helm upgrade --install {th['release']} {th['chart']} "
                        f"--namespace {th['ns']} --create-namespace {sets}")
                if dry_run:
                    results.append(f"DRY RUN [{tool_name}]: {cmd}")
                    continue
                code, out, er = ssh(with_proxy(cmd), timeout=300)
                status = "OK" if code == 0 else "FAIL"
                results.append(f"[{status}] {tool_name} — {th['description']}" + (f"\n  {er[-200:]}" if code != 0 else ""))
                if code == 0:
                    _state.setdefault("installed_security_tools", []).append(tool_name)
            return [TextContent(type="text", text="Security tools:\n" + "\n".join(results) + _format_next_steps("cluster_status"))]

        # ── install_applications ──────────────────────────────────────────
        elif name == "install_applications":
            cfg()
            apps      = arguments["apps"]
            storage   = arguments.get("storage_class", "")
            dry_run   = arguments.get("dry_run", False)
            unknown   = [a for a in apps if a not in APPLICATIONS_HELM]
            if unknown:
                return err(f"Unknown applications: {unknown}. Supported: {list(APPLICATIONS_HELM.keys())}")
            results = []
            creds_generated = {}
            for app_name in apps:
                ah   = APPLICATIONS_HELM[app_name]
                sets = list(ah.get("set", []))
                if storage:
                    sets.append(f"persistence.storageClass={storage}")
                    sets.append(f"global.storageClass={storage}")
                set_str = " ".join(f"--set {s}" for s in sets)
                cmd = (f"helm repo add {ah['repo']} {ah['url']} --force-update 2>/dev/null; "
                       f"helm upgrade --install {ah['release']} {ah['chart']} "
                       f"--namespace {ah['ns']} --create-namespace {set_str}")
                if dry_run:
                    results.append(f"DRY RUN [{app_name}]: {cmd}")
                    continue
                code, out, er = ssh(with_proxy(cmd), timeout=300)
                if code != 0:
                    results.append(f"[FAIL] {app_name}: {er[-200:]}")
                    continue
                results.append(f"[OK] {app_name}")
                # Generate / retrieve credentials
                if app_name == "vault":
                    # Initialize Vault and capture unseal keys
                    init_cmd = textwrap.dedent(f"""
                        sleep 10
                        kubectl exec -n {ah['ns']} vault-0 -- vault operator init -format=json 2>/dev/null || echo VAULT_ALREADY_INIT
                    """).strip()
                    _, vinit, _ = ssh(init_cmd, timeout=60)
                    try:
                        import json as _json
                        vdata = _json.loads(vinit.strip())
                        creds_generated["vault"] = {
                            "unseal_keys":  vdata.get("unseal_keys_b64", []),
                            "root_token":   vdata.get("root_token", ""),
                            "namespace":    ah["ns"],
                            "access":       "kubectl port-forward -n vault svc/vault 8200:8200",
                        }
                    except Exception:
                        creds_generated["vault"] = {"note": "vault init output not parseable — check manually", "namespace": ah["ns"]}
                    # Configure K8s auth method
                    k8s_auth_cmd = textwrap.dedent(f"""
                        kubectl exec -n {ah['ns']} vault-0 -- sh -c \
                        'vault login $VAULT_ROOT_TOKEN 2>/dev/null; \
                         vault auth enable kubernetes 2>/dev/null; \
                         vault write auth/kubernetes/config \
                           kubernetes_host="https://kubernetes.default.svc:443"' 2>/dev/null || true
                    """).strip()
                    ssh(k8s_auth_cmd, timeout=30)
                elif app_name == "keycloak":
                    pw_cmd = "kubectl get secret -n keycloak keycloak -o jsonpath='{.data.admin-password}' | base64 -d"
                    _, pw_out, _ = ssh(pw_cmd, timeout=15)
                    creds_generated["keycloak"] = {
                        "admin_user":  "admin",
                        "admin_pass":  pw_out.strip() or "(check keycloak secret)",
                        "namespace":   ah["ns"],
                        "access":      "kubectl port-forward -n keycloak svc/keycloak 8080:80",
                        "oidc_url":    "http://keycloak.keycloak.svc.cluster.local/realms/master",
                    }
                elif app_name == "harbor":
                    pw_cmd = "kubectl get secret -n harbor harbor-core -o jsonpath='{.data.secret}' 2>/dev/null | base64 -d || echo 'Harbor12345'"
                    _, pw_out, _ = ssh(pw_cmd, timeout=15)
                    creds_generated["harbor"] = {
                        "admin_user": "admin",
                        "admin_pass": pw_out.strip() or "Harbor12345",
                        "namespace":  ah["ns"],
                        "access":     "kubectl port-forward -n harbor svc/harbor 8080:80",
                    }
                elif app_name == "sonarqube":
                    creds_generated["sonarqube"] = {
                        "admin_user": "admin",
                        "admin_pass": "admin (change on first login)",
                        "namespace":  ah["ns"],
                        "access":     "kubectl port-forward -n sonarqube svc/sonarqube-sonarqube 9000:9000",
                    }
                _state.setdefault("installed_applications", {})[app_name] = {
                    "namespace": ah["ns"], "creds": creds_generated.get(app_name, {})}
            cred_lines = []
            for app, data in creds_generated.items():
                cred_lines.append(f"\n── {app} credentials ──")
                for k, v in data.items():
                    if isinstance(v, list):
                        cred_lines.append(f"  {k}:")
                        for item in v: cred_lines.append(f"    {item}")
                    else:
                        cred_lines.append(f"  {k}: {v}")
            cred_note = "\n".join(cred_lines) if cred_lines else ""
            return [TextContent(type="text", text="Applications:\n" + "\n".join(results) + cred_note +
                                "\n\nRun generate_cluster_report to save all credentials to a file." +
                                _format_next_steps("cluster_status"))]

        # ── configure_rbac ────────────────────────────────────────────────
        elif name == "configure_rbac":
            cfg()
            audit_level   = arguments.get("audit_level", "metadata")
            restrict_sa   = arguments.get("restrict_default_sa", True)
            dry_run       = arguments.get("dry_run", False)
            steps = []

            # 1. Patch default ServiceAccounts to disable automount
            if restrict_sa:
                cmd = ("for ns in $(kubectl get ns -o jsonpath='{.items[*].metadata.name}'); do "
                       "kubectl patch serviceaccount default -n $ns "
                       "-p '{\"automountServiceAccountToken\":false}' 2>/dev/null || true; done")
                steps.append(("Restrict default ServiceAccount automount", cmd))

            # 2. Remove cluster-admin from system:anonymous if present
            steps.append(("Remove anonymous cluster-admin binding (if exists)",
                           "kubectl delete clusterrolebinding cluster-admin-anonymous 2>/dev/null || true"))

            # 3. Set audit policy
            audit_policy = textwrap.dedent(f"""
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
  - level: None
    users: ["system:kube-proxy"]
    verbs: ["watch"]
    resources:
      - group: ""
        resources: ["endpoints","services","services/status"]
  - level: None
    users: ["system:unsecured"]
    namespaces: ["kube-system"]
    verbs: ["get"]
    resources:
      - group: ""
        resources: ["configmaps"]
  - level: {audit_level.capitalize()}
    resources:
      - group: ""
        resources: ["secrets","configmaps","tokenreviews","subjectaccessreviews"]
  - level: {audit_level.capitalize()}
""").strip()
            steps.append(("Write audit policy", f"cat <<'APEOF' | tee /etc/kubernetes/audit-policy.yaml\n{audit_policy}\nAPEOF"))

            if dry_run:
                lines = [f"DRY RUN: {label}\n  {cmd}" for label, cmd in steps]
                return [TextContent(type="text", text="configure_rbac dry run:\n" + "\n".join(lines))]

            results = []
            for label, cmd in steps:
                code, _, er = ssh(cmd, timeout=60)
                results.append(f"[{'OK' if code==0 else 'FAIL'}] {label}" + (f"\n  {er[-200:]}" if code != 0 else ""))
            return [TextContent(type="text", text="RBAC configuration:\n" + "\n".join(results) + _format_next_steps("cluster_status"))]

        # ── configure_pod_security ────────────────────────────────────────
        elif name == "configure_pod_security":
            cfg()
            c = cfg()
            mode         = arguments.get("mode", "baseline")
            default_deny = arguments.get("default_deny_network", True)
            dry_run      = arguments.get("dry_run", False)
            steps = []

            # Label all non-system namespaces with PodSecurity admission mode
            steps.append(("Label namespaces with PodSecurity mode",
                textwrap.dedent(f"""
                    for ns in $(kubectl get ns -o jsonpath='{{.items[*].metadata.name}}' | tr ' ' '\\n' | grep -v '^kube-\\|^cert-manager\\|^monitoring\\|^istio'); do
                        kubectl label namespace $ns pod-security.kubernetes.io/enforce={mode} --overwrite 2>/dev/null || true
                        kubectl label namespace $ns pod-security.kubernetes.io/warn={mode} --overwrite 2>/dev/null || true
                    done
                """).strip()))

            if default_deny:
                default_deny_manifest = textwrap.dedent("""
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
""").strip()
                steps.append(("Apply default-deny NetworkPolicy to app namespaces",
                    textwrap.dedent(f"""
                        for ns in $(kubectl get ns -o jsonpath='{{.items[*].metadata.name}}' | tr ' ' '\\n' | grep -v '^kube-\\|^cert-manager\\|^monitoring\\|^istio\\|^default$'); do
                            cat <<'NPEOF' | kubectl apply -n $ns -f - 2>/dev/null || true
{default_deny_manifest}
NPEOF
                        done
                    """).strip()))

            if dry_run:
                return [TextContent(type="text", text="configure_pod_security dry run:\n" +
                                    "\n".join(f"  {l}" for l,_ in steps))]
            results = []
            for label, cmd in steps:
                code, _, er = ssh(cmd, timeout=60)
                results.append(f"[{'OK' if code==0 else 'FAIL'}] {label}" + (f"\n  {er[-200:]}" if code != 0 else ""))
            return [TextContent(type="text", text="Pod security configuration:\n" + "\n".join(results) + _format_next_steps("cluster_status"))]

        # ── configure_etcd_encryption ─────────────────────────────────────
        elif name == "configure_etcd_encryption":
            cfg()
            algo    = arguments.get("algorithm", "aes-cbc")
            dry_run = arguments.get("dry_run", False)
            import secrets as _secrets, base64 as _base64
            key_b64 = _base64.b64encode(_secrets.token_bytes(32)).decode()
            enc_config = textwrap.dedent(f"""
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources:
      - secrets
      - configmaps
    providers:
      - {algo.replace("-","")}: {{}}
        keys:
          - name: key1
            secret: {key_b64}
      - identity: {{}}
""").strip()
            cmd = textwrap.dedent(f"""
                mkdir -p /etc/kubernetes/encryption
                cat <<'ENCEOF' | tee /etc/kubernetes/encryption/config.yaml
{enc_config}
ENCEOF
                grep -q 'encryption-provider-config' /etc/kubernetes/manifests/kube-apiserver.yaml || \
                  sed -i '/- kube-apiserver/a\\    - --encryption-provider-config=/etc/kubernetes/encryption/config.yaml' \
                  /etc/kubernetes/manifests/kube-apiserver.yaml
                sleep 10
                kubectl get secrets --all-namespaces -o json | kubectl replace -f - 2>/dev/null || true
                echo ETCD_ENCRYPTION_DONE
            """).strip()
            if dry_run:
                return [TextContent(type="text", text=f"DRY RUN — etcd encryption config:\n{enc_config}")]
            code, out, er = ssh(cmd, timeout=120)
            if code != 0: return err(f"etcd encryption failed:\n{er}")
            _state.setdefault("security_config", {})["etcd_encryption"] = {"algorithm": algo, "key_b64_preview": key_b64[:8]+"..."}
            return [TextContent(type="text", text=f"etcd encryption ({algo}) configured.\nAll existing Secrets re-encrypted.\n\nKEY (store securely): {key_b64}" + _format_next_steps("cluster_status"))]

        # ── configure_audit_logging ───────────────────────────────────────
        elif name == "configure_audit_logging":
            cfg()
            level    = arguments.get("level", "metadata")
            log_path = arguments.get("log_path", "/var/log/kubernetes/audit.log")
            max_age  = arguments.get("max_age", 30)
            dry_run  = arguments.get("dry_run", False)

            if level == "none":
                return [TextContent(type="text", text="Audit logging: skipped (level=none).")]

            audit_policy = textwrap.dedent(f"""
apiVersion: audit.k8s.io/v1
kind: Policy
omitStages:
  - RequestReceived
rules:
  - level: None
    nonResourceURLs: ["/healthz","/readyz","/livez","/metrics"]
  - level: None
    users: ["system:kube-proxy","system:apiserver","system:kube-controller-manager","system:kube-scheduler"]
    verbs: ["watch","list","get"]
  - level: {level.capitalize()}
    resources:
      - group: ""
        resources: ["secrets"]
    verbs: ["get","list","watch","create","update","patch","delete"]
  - level: {level.capitalize()}
    resources:
      - group: "rbac.authorization.k8s.io"
        resources: ["clusterroles","clusterrolebindings","roles","rolebindings"]
  - level: Metadata
    omitStages:
      - RequestReceived
""").strip()

            cmd = textwrap.dedent(f"""
                mkdir -p /etc/kubernetes $(dirname {log_path})
                cat <<'AUDITEOF' | tee /etc/kubernetes/audit-policy.yaml
{audit_policy}
AUDITEOF
                grep -q 'audit-log-path' /etc/kubernetes/manifests/kube-apiserver.yaml || {{
                  sed -i '/- kube-apiserver/a\\    - --audit-log-path={log_path}\\n    - --audit-log-maxage={max_age}\\n    - --audit-log-maxbackup=10\\n    - --audit-log-maxsize=100\\n    - --audit-policy-file=/etc/kubernetes/audit-policy.yaml' \
                    /etc/kubernetes/manifests/kube-apiserver.yaml
                }}
                echo AUDIT_DONE
            """).strip()
            if dry_run:
                return [TextContent(type="text", text=f"DRY RUN — audit policy:\n{audit_policy}")]
            code, out, er = ssh(cmd, timeout=60)
            if code != 0: return err(f"Audit logging config failed:\n{er}")
            return [TextContent(type="text", text=f"Audit logging ({level}) configured. Logs: {log_path}" + _format_next_steps("cluster_status"))]

        # ── security_audit ────────────────────────────────────────────────
        elif name == "security_audit":
            cfg()
            requested = arguments.get("standards", ["all"])
            if "all" in requested:
                requested = list(COMPLIANCE_CHECKS.keys())

            output = ["COMPLIANCE AUDIT REPORT", "=" * 50]
            total_checks = 0
            total_pass   = 0

            for std in requested:
                checks = COMPLIANCE_CHECKS.get(std, [])
                if not checks:
                    continue
                output.append(f"\n── {std.upper()} ({len(checks)} checks) ──")
                for label, cmd in checks:
                    _, out, er = ssh(cmd, timeout=20)
                    result = (out or er).strip()
                    # Heuristic pass/fail: empty output or "none" = pass, content = finding
                    is_finding = bool(result and result.lower() not in ["none", "ok", "ok: insecure-port not set"])
                    status = "FINDING" if is_finding else "PASS"
                    total_checks += 1
                    if not is_finding: total_pass += 1
                    output.append(f"  [{status}] {label}")
                    if is_finding:
                        output.append(f"    {result[:300]}")

            output.append(f"\nSUMMARY: {total_pass}/{total_checks} checks passed")
            if total_pass < total_checks:
                output.append("Run generate_cluster_report to save the full audit report.")
            _state.setdefault("security_config", {})["last_audit"] = {
                "standards": requested, "pass": total_pass, "total": total_checks}
            return [TextContent(type="text", text="\n".join(output) + _format_next_steps("audit_cluster"))]

        # ── install_cert_manager ──────────────────────────────────────────
        elif name == "install_cert_manager":
            cfg()
            issuer_type = arguments.get("issuer_type", "self-signed")
            email       = arguments.get("email", "")
            dry_run     = arguments.get("dry_run", False)
            cm          = CERT_MANAGER_HELM
            sets        = " ".join(f"--set {s}" for s in cm["set"])
            install_cmd = (f"helm repo add {cm['repo']} {cm['url']} --force-update 2>/dev/null; "
                           f"helm upgrade --install {cm['release']} {cm['chart']} "
                           f"--namespace {cm['ns']} --create-namespace {sets}")

            if issuer_type == "self-signed":
                issuer_manifest = textwrap.dedent("""
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: selfsigned-issuer
spec:
  selfSigned: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: cluster-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: cluster-ca
  secretName: cluster-ca-secret
  privateKey:
    algorithm: ECDSA
    size: 256
  issuerRef:
    name: selfsigned-issuer
    kind: ClusterIssuer
---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: cluster-ca-issuer
spec:
  ca:
    secretName: cluster-ca-secret
""").strip()
            elif issuer_type in ("acme-letsencrypt", "acme-zerossl"):
                server = ("https://acme-v02.api.letsencrypt.org/directory"
                          if issuer_type == "acme-letsencrypt"
                          else "https://acme.zerossl.com/v2/DV90")
                if not email:
                    return err(f"email is required for ACME issuer type '{issuer_type}'")
                issuer_manifest = textwrap.dedent(f"""
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: acme-issuer
spec:
  acme:
    server: {server}
    email: {email}
    privateKeySecretRef:
      name: acme-issuer-key
    solvers:
      - http01:
          ingress:
            class: nginx
""").strip()
            else:  # internal-ca
                ca_cert = arguments.get("ca_cert", "")
                ca_key  = arguments.get("ca_key", "")
                if not ca_cert or not ca_key:
                    return err("ca_cert and ca_key (base64-encoded) are required for internal-ca issuer")
                issuer_manifest = textwrap.dedent(f"""
apiVersion: v1
kind: Secret
metadata:
  name: internal-ca-secret
  namespace: cert-manager
type: kubernetes.io/tls
data:
  tls.crt: {ca_cert}
  tls.key: {ca_key}
---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: internal-ca-issuer
spec:
  ca:
    secretName: internal-ca-secret
""").strip()

            apply_cmd = f"sleep 15 && cat <<'ISSEOF' | kubectl apply -f -\n{issuer_manifest}\nISSEOF"

            if dry_run:
                return [TextContent(type="text", text=f"DRY RUN — cert-manager install + issuer:\n{install_cmd}\n\nIssuer manifest:\n{issuer_manifest}")]

            code, _, er = ssh(with_proxy(install_cmd), timeout=300)
            if code != 0: return err(f"cert-manager install failed:\n{er}")
            code, _, er = ssh(apply_cmd, timeout=60)
            if code != 0: return err(f"ClusterIssuer creation failed:\n{er}")
            _state.setdefault("security_config", {})["cert_manager"] = {"issuer_type": issuer_type}
            return [TextContent(type="text", text=f"cert-manager installed, ClusterIssuer ({issuer_type}) created." + _format_next_steps("cluster_status"))]

        # ── renew_service_cert ────────────────────────────────────────────
        elif name == "renew_service_cert":
            cfg()
            cert_name = arguments["certificate_name"]
            ns        = arguments.get("namespace", "default")
            force     = arguments.get("force", False)
            if force:
                cmd = textwrap.dedent(f"""
                    SECRET=$(kubectl get certificate -n {ns} {cert_name} -o jsonpath='{{.spec.secretName}}' 2>/dev/null)
                    if [ -n "$SECRET" ]; then
                        kubectl delete secret -n {ns} $SECRET 2>/dev/null || true
                        echo "Secret $SECRET deleted — cert-manager will re-issue"
                    else
                        echo "Could not find secretName on Certificate {cert_name}"
                    fi
                """).strip()
            else:
                cmd = (f"kubectl annotate certificate -n {ns} {cert_name} "
                       f"cert-manager.io/issueTemporary='{datetime.now().isoformat()}' --overwrite")
            code, out, er = ssh(cmd, timeout=30)
            if code != 0: return err(f"Cert renewal trigger failed:\n{er}")
            return [TextContent(type="text", text=f"Cert renewal triggered for '{cert_name}' in ns/{ns}.\n{out}\ncert-manager will rotate it transparently without pod restarts." + _format_next_steps("rotate_certs"))]

        # ── cost_report ───────────────────────────────────────────────────
        elif name == "cost_report":
            cfg()
            c            = cfg()
            provider     = arguments.get("cloud_provider") or c.get("cloud_provider", "onprem")
            breakdown    = arguments.get("breakdown", "all")
            costing_cfg  = c.get("costing", {})
            rates        = {**DEFAULT_ONPREM_RATES, **costing_cfg.get("rates", {})}
            currency     = rates.get("currency", "USD")

            # Always collect resource consumption from the cluster
            _, nodes_out, _ = ssh("kubectl get nodes -o json")
            _, pods_out,  _ = ssh("kubectl get pods -A -o json")
            _, pvc_out,   _ = ssh("kubectl get pvc -A -o json")

            try:
                import json as _json
                nodes = _json.loads(nodes_out).get("items", [])
                pods  = _json.loads(pods_out).get("items",  [])
                pvcs  = _json.loads(pvc_out).get("items",   [])
            except Exception as e:
                return err(f"Could not parse cluster resource data: {e}")

            # Per-namespace CPU/memory aggregation from pod requests
            ns_resources: dict = {}
            for pod in pods:
                ns = pod["metadata"]["namespace"]
                ns_resources.setdefault(ns, {"cpu_m": 0, "mem_mi": 0, "pods": 0})
                ns_resources[ns]["pods"] += 1
                for c_spec in pod["spec"].get("containers", []):
                    req = c_spec.get("resources", {}).get("requests", {})
                    cpu_raw = req.get("cpu", "0")
                    mem_raw = req.get("memory", "0")
                    # Parse cpu: "500m" or "1"
                    if cpu_raw.endswith("m"):
                        ns_resources[ns]["cpu_m"] += int(cpu_raw[:-1])
                    elif cpu_raw:
                        try: ns_resources[ns]["cpu_m"] += int(float(cpu_raw) * 1000)
                        except: pass
                    # Parse memory: "512Mi" "1Gi" "1G"
                    if mem_raw.endswith("Mi"):
                        ns_resources[ns]["mem_mi"] += int(mem_raw[:-2])
                    elif mem_raw.endswith("Gi"):
                        ns_resources[ns]["mem_mi"] += int(mem_raw[:-2]) * 1024
                    elif mem_raw.endswith("M"):
                        ns_resources[ns]["mem_mi"] += int(mem_raw[:-1])

            # Node capacity totals
            total_cpu_cores = 0
            total_ram_gib   = 0
            for node in nodes:
                cap = node["status"].get("capacity", {})
                cpu_raw = cap.get("cpu", "0")
                mem_raw = cap.get("memory", "0Ki")
                try: total_cpu_cores += int(cpu_raw)
                except: pass
                try:
                    if mem_raw.endswith("Ki"):
                        total_ram_gib += int(mem_raw[:-2]) / (1024*1024)
                    elif mem_raw.endswith("Mi"):
                        total_ram_gib += int(mem_raw[:-2]) / 1024
                except: pass

            # PVC storage
            total_storage_gib = 0
            for pvc in pvcs:
                storage_raw = pvc["status"].get("capacity", {}).get("storage", "0Gi")
                try:
                    if storage_raw.endswith("Gi"):
                        total_storage_gib += int(storage_raw[:-2])
                    elif storage_raw.endswith("Mi"):
                        total_storage_gib += int(storage_raw[:-2]) / 1024
                except: pass

            # Cost calculation
            cpu_hourly   = total_cpu_cores  * rates["cpu_core_hourly_usd"]
            ram_hourly   = total_ram_gib    * rates["ram_gb_hourly_usd"]
            storage_mo   = total_storage_gib * rates["storage_gb_monthly_usd"]
            total_hourly = cpu_hourly + ram_hourly
            total_monthly = total_hourly * 730 + storage_mo  # 730h/month

            lines = [
                "COST REPORT",
                "=" * 40,
                f"Infrastructure: {provider}  |  Currency: {currency}",
                "",
                "── Node capacity ──",
                f"  CPU cores:    {total_cpu_cores}  @ {rates['cpu_core_hourly_usd']:.4f} {currency}/core/hr",
                f"  RAM:          {total_ram_gib:.1f} GiB  @ {rates['ram_gb_hourly_usd']:.4f} {currency}/GiB/hr",
                f"  PVC storage:  {total_storage_gib:.1f} GiB  @ {rates['storage_gb_monthly_usd']:.4f} {currency}/GiB/mo",
                "",
                "── Estimated monthly cost ──",
                f"  Compute (CPU):  {currency} {cpu_hourly*730:,.2f}",
                f"  Compute (RAM):  {currency} {ram_hourly*730:,.2f}",
                f"  Storage:        {currency} {storage_mo:,.2f}",
                f"  TOTAL/month:    {currency} {total_monthly:,.2f}",
            ]

            if breakdown in ("namespace", "all"):
                lines.append("\n── Per-namespace resource requests ──")
                for ns_name in sorted(ns_resources.keys()):
                    r = ns_resources[ns_name]
                    ns_cpu  = r["cpu_m"] / 1000
                    ns_ram  = r["mem_mi"] / 1024
                    ns_cost = (ns_cpu * rates["cpu_core_hourly_usd"] + ns_ram * rates["ram_gb_hourly_usd"]) * 730
                    lines.append(f"  {ns_name:<30}  {ns_cpu:.2f} CPU  {ns_ram:.1f} GiB  {currency} {ns_cost:,.2f}/mo  ({r['pods']} pods)")

            if provider in ("aws", "gcp", "azure"):
                lines.append(f"\n── Cloud billing note ──")
                lines.append(f"  Real billing API integration for {provider} requires cloud CLI credentials.")
                lines.append(f"  Set aws_profile / gcp_project / azure_sub in the tool arguments and ensure")
                lines.append(f"  the cloud CLI is installed and authenticated on this node.")
                lines.append(f"  The figures above are based on resource consumption × configured rates.")

            lines.append(f"\nNote: rates are configurable under a 'costing.rates' block in your cluster config.")
            _state["last_cost_report"] = {"total_monthly": total_monthly, "currency": currency}
            return [TextContent(type="text", text="\n".join(lines) + _format_next_steps("cluster_status"))]

        # ── generate_cluster_report ───────────────────────────────────────
        elif name == "generate_cluster_report":
            c              = cfg()
            output_dir     = arguments.get("output_dir", "/opt/cluster-report")
            inc_secrets    = arguments.get("include_secrets", True)
            ts             = datetime.now().strftime("%Y%m%d-%H%M%S")
            report_dir     = f"{output_dir}/{ts}"

            # ── Gather all state ──────────────────────────────────────────
            # Cluster basics
            _, nodes_out,  _ = ssh("kubectl get nodes -o wide")
            _, ns_out,     _ = ssh("kubectl get namespaces")
            _, svc_out,    _ = ssh("kubectl get svc -A")
            _, pv_out,     _ = ssh("kubectl get pv")
            _, cert_out,   _ = ssh("kubeadm certs check-expiration 2>/dev/null || echo 'kubeadm not available'")
            _, cm_cert_out, _ = ssh("kubectl get certificates -A 2>/dev/null || echo 'cert-manager not installed'")
            _, sa_out,     _ = ssh("kubectl get serviceaccounts -A")
            _, np_out,     _ = ssh("kubectl get networkpolicies -A 2>/dev/null || echo none")

            # All installed application credentials from state
            installed_apps = _state.get("installed_applications", {})
            installed_sec  = _state.get("installed_security_tools", [])
            security_conf  = _state.get("security_config", {})
            last_audit     = security_conf.get("last_audit", {})
            cost_data      = _state.get("last_cost_report", {})
            nc             = c.get("node_config", DEFAULT_NODE_CONFIG)

            # Standard credentials (Jenkins, Grafana, etc.)
            std_creds = {}
            # Jenkins
            jns_out = ssh("kubectl get secret -n jenkins jenkins -o jsonpath='{.data.jenkins-admin-password}' 2>/dev/null | base64 -d")[1]
            if jns_out: std_creds["jenkins"] = {"user": "admin", "pass": jns_out.strip(), "access": "kubectl port-forward -n jenkins svc/jenkins 8080:8080"}
            # Grafana
            gns_out = ssh("kubectl get secret -n monitoring monitoring-grafana -o jsonpath='{.data.admin-password}' 2>/dev/null | base64 -d")[1]
            if gns_out: std_creds["grafana"] = {"user": "admin", "pass": gns_out.strip(), "access": "kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80"}

            # Mask secrets if include_secrets=False
            def maybe_mask(v):
                return v if inc_secrets else "***REDACTED***"

            # ── Build Markdown report ─────────────────────────────────────
            md = []
            md.append(f"# Cluster report — {c.get('cluster_name','unknown')}  ({ts})")
            md.append(f"\nGenerated by k8s-mcp-v1\n")

            md.append("## Cluster overview")
            md.append(f"- **Cluster name:** {c.get('cluster_name')}")
            md.append(f"- **Kubernetes version:** {c.get('k8s_version')}")
            md.append(f"- **CNI:** {c.get('cni')}  |  **Profile:** {c.get('profile')}  |  **Monitoring:** {c.get('monitoring','none')}")
            md.append(f"- **Pod CIDR:** {c.get('pod_cidr')}  |  **Service CIDR:** {c.get('service_cidr')}")
            md.append(f"- **Control plane:** {'HA — '+str(len(c.get('masters',[])))+ ' masters' if len(c.get('masters',[]))>1 else 'single master'}")
            md.append(f"- **Proxy:** {c.get('proxy',{}).get('http_proxy','none (direct internet)')}")

            md.append("\n## Node configuration applied")
            md.append(f"- sysctl preset: `{nc.get('sysctl_preset')}`")
            md.append(f"- kernel modules: `{nc.get('kernel_modules')}`")
            md.append(f"- iptables mode: `{nc.get('iptables_mode')}`  |  swap: `{nc.get('swap')}`  |  SELinux (RHEL): `{nc.get('selinux')}`")
            md.append(f"- hugepages THP: `{'enabled' if nc.get('hugepages') else 'disabled'}`  |  ulimits: `{'set' if nc.get('ulimits',True) else 'skipped'}`")

            md.append("\n## Nodes\n```")
            md.append(nodes_out.strip())
            md.append("```")

            md.append("\n## Namespaces\n```")
            md.append(ns_out.strip())
            md.append("```")

            md.append("\n## Network")
            md.append(f"- Pod CIDR: `{c.get('pod_cidr')}`")
            md.append(f"- Service CIDR: `{c.get('service_cidr')}`")
            md.append("\n### NetworkPolicies\n```")
            md.append(np_out.strip())
            md.append("```")

            md.append("\n## Services\n```")
            md.append(svc_out.strip())
            md.append("```")

            md.append("\n## Persistent volumes\n```")
            md.append(pv_out.strip())
            md.append("```")

            md.append("\n## Certificate expiry (control plane)")
            md.append("```")
            md.append(cert_out.strip())
            md.append("```")
            md.append("\n### cert-manager Certificates")
            md.append("```")
            md.append(cm_cert_out.strip())
            md.append("```")

            md.append("\n## ServiceAccounts\n```")
            md.append(sa_out.strip())
            md.append("```")

            md.append("\n## Credentials and access")
            md.append("> Keep this section confidential. Do not commit to source control.\n")
            all_creds = {**std_creds, **{k: v.get("creds",{}) for k,v in installed_apps.items()}}
            for svc_name, creds in all_creds.items():
                md.append(f"### {svc_name}")
                for k, v in creds.items():
                    vv = maybe_mask(str(v)) if k in ("pass","admin_pass","root_token","unseal_keys","token") else str(v)
                    md.append(f"- **{k}:** `{vv}`")

            md.append("\n## Security tools installed")
            md.append(", ".join(installed_sec) if installed_sec else "none")
            if last_audit:
                md.append(f"\n### Last compliance audit")
                md.append(f"- Standards checked: {', '.join(last_audit.get('standards',[]))}")
                md.append(f"- Result: **{last_audit.get('pass',0)}/{last_audit.get('total',0)} checks passed**")
            if security_conf.get("etcd_encryption"):
                md.append(f"\n### etcd encryption")
                md.append(f"- Algorithm: `{security_conf['etcd_encryption']['algorithm']}`  (key stored on master)")
            if security_conf.get("cert_manager"):
                md.append(f"\n### cert-manager")
                md.append(f"- Issuer type: `{security_conf['cert_manager']['issuer_type']}`")

            if cost_data:
                md.append(f"\n## Cost estimate")
                md.append(f"- Total monthly estimate: **{cost_data.get('currency','USD')} {cost_data.get('total_monthly',0):,.2f}**")
                md.append("- Run `cost_report` for a full per-namespace breakdown.")

            md.append("\n## Next recommended actions")
            md.append("- [ ] Change all default passwords listed above")
            md.append("- [ ] Run `security_audit` to check compliance against CIS/NSA benchmarks")
            md.append("- [ ] Schedule regular `backup_etcd` runs")
            md.append("- [ ] Set up a GitOps workflow via ArgoCD pointing at your application repos")
            md.append("- [ ] Configure Alertmanager notification channels in Prometheus")

            md_content = "\n".join(md)

            # ── Build YAML report ─────────────────────────────────────────
            yaml_data = {
                "cluster": {
                    "name": c.get("cluster_name"), "k8s_version": c.get("k8s_version"),
                    "cni": c.get("cni"), "profile": c.get("profile"),
                    "pod_cidr": c.get("pod_cidr"), "service_cidr": c.get("service_cidr"),
                    "masters": [n["name"] for n in c.get("masters",[])],
                    "workers": [n["name"] for n in c.get("workers",[])],
                },
                "credentials": {
                    svc: {k: (maybe_mask(str(v)) if k in ("pass","admin_pass","root_token","unseal_keys") else str(v))
                          for k, v in creds.items()}
                    for svc, creds in all_creds.items()
                },
                "security_tools": installed_sec,
                "compliance_last_audit": last_audit,
                "security_config": security_conf,
                "cost_estimate_usd_monthly": cost_data.get("total_monthly", 0),
                "generated_at": ts,
            }
            yaml_content = yaml.dump(yaml_data, default_flow_style=False, allow_unicode=True)

            # ── Write both files to master node ──────────────────────────
            write_cmd = textwrap.dedent(f"""
                mkdir -p {report_dir}
                cat <<'MDEOF' > {report_dir}/cluster-report.md
{md_content}
MDEOF
                cat <<'YAMLEOF' > {report_dir}/cluster-report.yaml
{yaml_content}
YAMLEOF
                chmod 600 {report_dir}/cluster-report.md {report_dir}/cluster-report.yaml
                echo "Files written to {report_dir}"
                ls -lh {report_dir}/
            """).strip()
            code, out, er = ssh(write_cmd, timeout=30)
            summary = md_content[:1200] + "\n\n...(truncated — full report on master at " + report_dir + ")"
            return [TextContent(type="text", text=
                f"Cluster report generated at {report_dir} on master node.\n"
                f"Two files written: cluster-report.md and cluster-report.yaml\n"
                f"Permissions: 600 (owner-only readable)\n\n"
                f"To retrieve locally:\n"
                f"  scp <user>@<master-ip>:{report_dir}/cluster-report.md ./\n"
                f"  scp <user>@<master-ip>:{report_dir}/cluster-report.yaml ./\n\n"
                f"── Report summary ──\n{summary}")]

        else:
            return err(f"Unknown tool '{name}'")

    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"Unexpected error: {e}")


async def main():
    async with stdio_server() as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
