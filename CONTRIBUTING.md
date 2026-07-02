# Contributing to k8s-mcp-v1

Thank you for wanting to improve this project. This guide explains how to add new tools, fix bugs, add OS support, and contribute example configs — and how to verify your changes before submitting.

---

## Getting started

```bash
git clone https://github.com/<your-org>/k8s-mcp-v1.git
cd k8s-mcp-v1
pip install mcp paramiko pyyaml
python3 k8s_factory_mcp.py   # should start without errors
```

---

## Project structure

```
k8s_factory_mcp.py   — the entire MCP server (one file by design)
cluster_config.yaml  — fully annotated reference config
README.md            — complete documentation (28 sections)
TODO.md              — feature matrix: what's in, what's next, how to contribute
CONTRIBUTING.md      — this file
LICENSE              — Apache 2.0
examples/
  single-node-dev.yaml
  3-node-production.yaml
  5-node-ha.yaml
  openstack-rhel-proxy.yaml
  gpu-ml-cluster.yaml
```

The entire project intentionally lives in one Python file. This makes it easy to copy to any server, inspect in one scroll, and register as an MCP server without packaging or builds.

---

## How to add a new tool

A tool is a function exposed to Claude AI. Every tool has three parts:

### 1. Add constants (if needed)

If your tool has a set of valid option values or Helm chart details, add them near the top of the file with the other `SUPPORTED_*` constants or `*_HELM` dictionaries.

```python
SUPPORTED_MY_FEATURE = ["option-a", "option-b", "option-c"]

MY_FEATURE_HELM = {
    "option-a": {
        "repo": "myrepo", "url": "https://charts.example.com",
        "chart": "myrepo/my-chart", "release": "my-release", "ns": "my-namespace",
        "description": "What this option does",
    }
}
```

### 2. Add the Tool definition in `list_tools()`

```python
Tool(name="my_new_tool",
     description=(
         "One or two sentences explaining what this tool does and when Claude "
         "should call it. If the user hasn't specified required choices, say "
         "that Claude should ask before calling."),
     inputSchema={"type":"object","properties":{
         "my_param": {"type":"string","enum":["option-a","option-b"],
                      "description":"What this parameter controls"},
         "dry_run":  {"type":"boolean","default":False}},
         "required":["my_param"]}),
```

### 3. Add the handler in `call_tool()`

Find the `else: return err(f"Unknown tool")` at the bottom and add your handler before it:

```python
elif name == "my_new_tool":
    cfg()  # call this if your tool needs the cluster config
    param   = arguments["my_param"]
    dry_run = arguments.get("dry_run", False) or _gdry

    if dry_run:
        return done(f"DRY RUN: would run X with param={param}")

    # Do the work
    code, out, er = ssh("your kubectl or helm command here")
    if code != 0:
        return err(f"my_new_tool failed:\n{er}")

    # save_cluster if you mutated _state
    return done(f"my_new_tool succeeded:\n{out}" + _format_next_steps("my_new_tool"),
                f"param={param}")
```

Key helpers available inside `call_tool()`:

| Helper | What it does |
|--------|-------------|
| `cfg()` | Returns the current cluster config dict. Raises ValueError if not set. |
| `ssh(cmd, node, timeout)` | Run a command on the first master (or a specific node) |
| `err(msg)` | Return an error result AND log it to the audit trail |
| `done(text, note)` | Return a success result, save state to disk, log to audit trail |
| `with_proxy(cmd)` | Prepend proxy env exports to a command |
| `all_nodes()` | List of all master + worker node dicts |
| `_gdry` | True if global_dry_run is set in the cluster config |

### 4. Add next-step options

In the `NEXT_STEPS` dictionary, add an entry for your tool showing what a user might want to do after it:

```python
"my_new_tool": [
    ("cluster_status",   "Verify the cluster is still healthy"),
    ("my_new_tool",      "Run again with different options"),
],
```

Also add your tool to the next-steps of tools that naturally lead to it.

### 5. Verify syntax

```bash
python3 -W error -c "import ast; ast.parse(open('k8s_factory_mcp.py').read()); print('OK')"
```

### 6. Test it

Register the server and open a Claude session:
```bash
claude mcp add k8s-factory -- python3 ./k8s_factory_mcp.py
claude
```

Then call your tool conversationally.

---

## How to add a new OS family

The OS family system is in three places:

1. **`PKG_COMMANDS` dict** — add an entry with `update`, `install`, `hold`, `unhold`, `install_pinned`, `base_pkgs`, and `repo_setup` keys matching the existing entries.

2. **`detect_os_family()` function** — add detection logic mapping `/etc/os-release` ID values to your new family name.

3. **`prerequisites_script()` function** — add a branch for your OS family's repo bootstrap (equivalent to what the `rhel` or `debian` branches do).

4. **`SUPPORTED_OS_FAMILIES`** — add the new family name.

5. **`node_prep_script()`** — add a branch for the `containerd_cgroup_fix`, `install_k8s_pkgs`, and `hold_cmd` that are specific to your OS's package manager syntax.

---

## How to add a compliance check

In the `COMPLIANCE_CHECKS` dict, add a key for the standard name (or add checks to an existing standard):

```python
COMPLIANCE_CHECKS["my-standard"] = [
    ("Check description",
     "kubectl command or shell command that checks it"),
]
```

The `security_audit` tool picks it up automatically. Add the key to `SUPPORTED_COMPLIANCE`.

---

## How to add an example config

Create a YAML file in `examples/` following the naming pattern:

```
examples/<use-case>.yaml
```

The file should:
- Have a comment block at the top explaining the use case and minimum requirements
- Have every non-obvious field commented
- Use realistic but anonymised IPs (`192.168.1.x` or `10.0.0.x`)
- Use `~/.ssh/id_rsa` as the key path (users replace this with their actual path)

---

## How to update documentation

`README.md` is the source of truth for all documentation. It has 28 sections. If you add a tool, add it to:
- Section 9 (All 34 tools — complete reference) with its parameters documented
- Section 22 (Workflow walkthrough) if it fits into the main flow
- Section 28 (Example prompts) with at least one example prompt

`TODO.md` tracks what is and isn't implemented. Move items from the To-do section to the What's implemented section when you build them.

---

## Submitting a pull request

1. Fork the repo and create a branch: `git checkout -b add-my-feature`
2. Make your changes
3. Run the syntax check: `python3 -W error -c "import ast; ast.parse(open('k8s_factory_mcp.py').read())"`
4. Update `TODO.md` — move completed items, add your feature to the implemented table
5. Update `README.md` — document any new tool or config option
6. Add an example config to `examples/` if relevant
7. Open a pull request with:
   - A one-paragraph description of what the feature does
   - Which TODO item it addresses (or a new gap it fills)
   - How you tested it

---

## Code style

- One file (`k8s_factory_mcp.py`) — do not split into modules
- Every tool handler fits in one `elif` block
- Every tool has `dry_run` support if it modifies infrastructure
- Use `done()` for success returns and `err()` for error returns in all tool handlers
- Secrets in log output must be masked — check `_audit()` for the masking pattern
- Shell scripts generated by the MCP use `set -euo pipefail` and are idempotent where possible
- Add a `# ── tool name ──` comment above each handler for easy navigation

---

## Questions

Open a GitHub Issue with the `question` label. Include:
- Your OS (both the executor node and the cluster nodes)
- Your network environment (direct internet, proxy, air-gapped)
- The exact error message or unexpected behaviour

---

Thank you for contributing.
