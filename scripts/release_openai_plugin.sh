#!/usr/bin/env bash
# Create GitHub release v<plugin version> with the OpenAI plugin ZIP attached,
# once per version. Run by .github/workflows/openai-plugin.yml on pushes to main.
#
# Usage: release_openai_plugin.sh <zip> <target-commit>
#
# - No release for the version yet: create it (tag at <target-commit>).
# - Release exists with an identical ZIP: nothing to do.
# - Release exists with a different ZIP: warn. Releases are per-version
#   snapshots and OpenAI needs a new version number for each package update,
#   so a listing or skill change on main ships with the next version bump.
set -euo pipefail

zip=${1:?usage: release_openai_plugin.sh <zip> <target-commit>}
target=${2:?usage: release_openai_plugin.sh <zip> <target-commit>}

version=$(unzip -p "$zip" plugin.json | jq -er .version)
tag="v${version}"
asset=$(basename "$zip")
sha=$(sha256sum "$zip" | cut -d' ' -f1)
summary=${GITHUB_STEP_SUMMARY:-/dev/stdout}

if ! gh release view "$tag" >/dev/null 2>&1; then
  notes="OpenAI plugin package for the Senzing MCP server v${version}.

Upload \`${asset}\` at https://platform.openai.com/plugins → Senzing → Upload new version.

SHA-256: \`${sha}\`"
  gh release create "$tag" "$zip" --target "$target" --title "$tag" --notes "$notes"
  echo "Created release ${tag} with ${asset} (sha256 ${sha})." >> "$summary"
  exit 0
fi

previous=$(mktemp -d)
trap 'rm -rf "$previous"' EXIT
if gh release download "$tag" --pattern "$asset" --dir "$previous" 2>/dev/null \
  && cmp -s "$zip" "$previous/$asset"; then
  echo "Release ${tag} already has this ${asset}; nothing to do." >> "$summary"
  exit 0
fi

msg="Release ${tag} exists but its ${asset} differs from main (or is missing). OpenAI needs a new version number for a package update, so this change ships with the next version bump."
echo "::warning::${msg}"
echo "${msg}" >> "$summary"
