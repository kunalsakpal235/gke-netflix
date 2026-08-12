#!/usr/bin/env bash
#
# cleanup-old-images.sh
#
# Keeps the N most recent image versions per service in Artifact Registry,
# deletes everything older. Defaults to DRY RUN (shows what would be deleted,
# deletes nothing) - pass --delete to actually perform the deletion.
#
# Usage:
#   ./cleanup-old-images.sh              # dry run (safe, default)
#   ./cleanup-old-images.sh --delete     # actually deletes
#
# Edit the CONFIG section below to change project/region/services/keep-count.

set -euo pipefail

# ---------- CONFIG - edit these as needed ----------
PROJECT="devops-1-502311"
REGION="asia-south1"
REPO_NAME="streaming-images"
SERVICES=(catalog-service user-service api-gateway frontend playback-service)
KEEP_COUNT=2
# ----------------------------------------------------

DRY_RUN=true
if [[ "${1:-}" == "--delete" ]]; then
  DRY_RUN=false
fi

if $DRY_RUN; then
  echo "### DRY RUN MODE - nothing will be deleted. Re-run with --delete to actually delete. ###"
else
  echo "### DELETE MODE - old images will be permanently removed. ###"
fi
echo ""

for svc in "${SERVICES[@]}"; do
  echo "=== ${svc} ==="
  REPO="${REGION}-docker.pkg.dev/${PROJECT}/${REPO_NAME}/${svc}"

  # List all versions, newest first. Skip lines 1-N (the ones to keep),
  # everything after that is a deletion candidate.
  mapfile -t all_versions < <(
    gcloud artifacts docker images list "$REPO" \
      --format="value(version)" --sort-by="~createTime" 2>/dev/null
  )

  total="${#all_versions[@]}"
  if (( total <= KEEP_COUNT )); then
    echo "  Only ${total} image(s) found - nothing older than the ${KEEP_COUNT} to keep. Skipping."
    echo ""
    continue
  fi

  to_delete=("${all_versions[@]:KEEP_COUNT}")
  echo "  Found ${total} image(s). Keeping ${KEEP_COUNT} newest, deleting ${#to_delete[@]} older one(s):"

  for digest in "${to_delete[@]}"; do
    if $DRY_RUN; then
      echo "    [DRY RUN] would delete: ${svc}@${digest}"
    else
      echo "    Deleting: ${svc}@${digest}"
      gcloud artifacts docker images delete "${REPO}@${digest}" --quiet --delete-tags
    fi
  done
  echo ""
done

echo "### Done. ###"
if $DRY_RUN; then
  echo "This was a dry run - nothing was deleted. Re-run with --delete to actually delete the images listed above."
fi
