"""
k8s_factory_mcp.py  v3.1
=========================
K8s Cluster Factory MCP Server — OS-independent, HA-aware, Proxy-aware Edition

NEW in v3.1 (on top of v3.0):
  - Corporate proxy support — a top-level `proxy` block in the cluster config
    (http_proxy, https_proxy, no_proxy) is applied automatically to every
    network-touching command across the whole lifecycle: apt/dnf/zypper package
    installs, containerd (via its own systemd drop-in, since daemons don't
    inherit SSH shell env vars), curl-based repo key fetches, helm repo add /
    helm upgrade, and kubectl apply -f <url>. No per-tool flags needed — set it
    once in plan_cluster's config and every subsequent tool call honors it.

NEW in v3.0 (on top of v2's 21 tools):
  - OS auto-detection per node (Ubuntu/Debian/RHEL/CentOS/Rocky/Alma/SUSE) —
    every script branches on the detected package manager (apt / dnf / yum / zypper)
  - True multi-master HA support — kubeadm init --upload-certs + join --control-plane
    on additional masters, kube-vip / external LB endpoint support
  - SSH concurrency everywhere — upgrade_cluster, scale_cluster, destroy_cluster,
    node_diagnostics now parallelize where the operation allows it (master upgrade
    stays serial-then-workers-parallel-in-batches; true rolling steps stay ordered)
  - install_monitoring — dedicated tool, choose kube-prometheus-stack alone or
    + Loki, selected at plan time or call time
  - install_jenkins — Jenkins-in-cluster via Helm, ClusterIP-only, persistent volume,
    pre-wired to use the cluster's own kubeconfig as a Kubernetes cloud agent target

Requirements:
  pip install mcp paramiko pyyaml

Register with Claude Code:
  claude mcp add k8s-factory -- python3 ~/mcp-servers/k8s_factory_mcp.py
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

# ─────────────────────────────────────────────────────────────────────────────
# Proxy support — every script that touches the network (apt/dnf/zypper, curl,
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
        ("install_monitoring", "Set up monitoring (Prometheus, or Prometheus + Loki)"),
        ("install_jenkins",    "Set up an in-cluster Jenkins for CI/CD"),
        ("cluster_status",     "Verify everything — check nodes, system pods, and unhealthy pods"),
        ("provision_namespace","Onboard the first team — create a namespace with quotas and RBAC"),
        ("backup_etcd",        "Take a baseline backup now that the cluster is fully built"),
    ],
    "install_monitoring": [
        ("install_jenkins",   "Also set up Jenkins for CI/CD in the same cluster"),
        ("cluster_status",    "Confirm the monitoring pods came up healthy"),
        ("manage_kubeconfig", "Generate a kubeconfig for someone who needs Grafana/Prometheus access"),
    ],
    "install_jenkins": [
        ("cluster_status",   "Confirm the Jenkins pod is Running"),
        ("stream_logs",      "Tail Jenkins controller logs to watch first boot"),
        ("manage_kubeconfig","Generate the kubeconfig Jenkins itself would use as a Kubernetes cloud agent"),
    ],
    "cluster_status": [
        ("install_monitoring", "Set up monitoring if you haven't yet"),
        ("install_jenkins",    "Set up Jenkins if you haven't yet"),
        ("provision_namespace","Create a namespace for a team"),
        ("migrate_workload",   "Migrate an existing docker-compose service onto this cluster"),
        ("backup_etcd",        "Take an etcd backup"),
        ("scale_cluster",      "Add more worker or master nodes"),
        ("audit_cluster",      "Run a security and config audit"),
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

def node_prep_script(k8s_version: str, os_family: str, proxy_cfg: dict | None = None) -> str:
    """Build the node-prep script for the given OS family (debian/rhel/suse).
    If proxy_cfg is set, proxy env vars are exported at the top of the script
    and written into the package manager's own config file, and containerd
    gets a systemd drop-in so the daemon itself can reach the network too."""
    pkg = PKG_COMMANDS[os_family]
    repo_setup = pkg["repo_setup"].format(k8s_version=k8s_version)

    proxy_exports = proxy_env_exports(proxy_cfg)
    containerd_proxy = containerd_proxy_dropin(proxy_cfg)

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
            setenforce 0 2>/dev/null || true
            sed -i 's/^SELINUX=enforcing/SELINUX=permissive/' /etc/selinux/config 2>/dev/null || true
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

    return textwrap.dedent(f"""
        set -euo pipefail
        {proxy_exports}{pkg_proxy_conf}
        swapoff -a
        sed -i '/[[:space:]]swap[[:space:]]/ s/^/#/' /etc/fstab 2>/dev/null || true
        cat <<EOF | tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF
        modprobe overlay && modprobe br_netfilter
        cat <<EOF | tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
        sysctl --system >/dev/null
        {pkg["update"]}
        {pkg["install"].format(pkgs=pkg["base_pkgs"])}
        {containerd_cgroup_fix}
        {containerd_proxy}
        systemctl restart containerd && systemctl enable containerd
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
            note = ""
            if "os_family" not in str(arguments["config"]):
                note = ("\n\nNote: no os_family was specified per node \u2014 prepare_nodes will SSH in and "
                        "auto-detect each node's OS (Ubuntu/Debian, RHEL/CentOS/Rocky/Alma, or SUSE) and use "
                        "the matching package manager automatically. Nodes can run different OSes.")
            if not proxy_cfg:
                note += ("\n\nNote: no proxy block was specified. If your nodes only reach the internet "
                         "through a corporate proxy, add a top-level 'proxy' block with http_proxy/https_proxy "
                         "(and optionally no_proxy) before running prepare_nodes, or every package install and "
                         "Helm chart download will fail with a network timeout.")
            return [TextContent(type="text", text="PLAN:\n" + yaml.dump(plan, default_flow_style=False) + note + _format_next_steps("plan_cluster"))]

        # ── prepare_nodes ─────────────────────────────────────────────────
        elif name == "prepare_nodes":
            c = cfg()
            nodes = all_nodes()
            dry_run = arguments.get("dry_run", False)
            pcfg = proxy()

            if dry_run:
                sample = node_prep_script(c["k8s_version"], "debian", pcfg)
                proxy_line = f"Proxy configured: {pcfg.get('http_proxy', pcfg.get('https_proxy'))}\n\n" if pcfg else "No proxy configured.\n\n"
                return [TextContent(type="text", text=
                    proxy_line + "DRY RUN \u2014 OS will be auto-detected per node; example script for a Debian-family node:\n\n" + sample)]

            os_results = detect_all_nodes_os(nodes)
            _state["os_cache"] = os_results
            for node in nodes:
                if node.get("os_family", "auto") == "auto":
                    node["os_family"] = os_results[node["name"]]["os_family"]

            pairs = [(node, node_prep_script(c["k8s_version"], node["os_family"], pcfg)) for node in nodes]
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

                prep_pairs = [(n, node_prep_script(c["k8s_version"], n["os_family"], proxy())) for n in nodes]
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
