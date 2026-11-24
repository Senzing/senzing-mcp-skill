#!/usr/bin/env bash
# Attach a plugin package ZIP to GitHub release v<version>, once per version.
# Run by .github/workflows/plugin-packages.yml on pushes to main, once per
# package (OpenAI, Microsoft 365), one after the other in the same job so the
# two never race to create the release.
#
# Usage: release_plugin.sh <zip> <target-commit> <upload-instructions> [<release-version>]
#
# The release version is <release-version> when given, else the "version" in
# the ZIP's root JSON manifest. The Microsoft 365 app has its own app version
# (in its ZIP name), so it passes the skill version to land in the same release.
# - No release for the version yet: create it (tag at <target-commit>) with the ZIP.
# - Release exists without this ZIP: upload it and add its line to the notes.
# - Release exists with an identical ZIP: nothing to do.
# - Release exists with a different ZIP: warn. Releases are per-version
#   snapshots and OpenAI and Partner Center need a new version number for each
#   package update, so a listing or skill change on main ships with the next
#   version bump (for Microsoft 365, the next app_version bump: a new ZIP name).
set -euo pipefail

usage="usage: release_plugin.sh <zip> <target-commit> <upload-instructions> [<release-version>]"
zip=${1:?$usage}
target=${2:?$usage}
where=${3:?$usage}
version=${4:-}

if [[ -z $version ]]; then
  members=$(unzip -Z1 "$zip" | grep -E '^[^/]+\.json$' || true)
  version=$(for member in $members; do unzip -p "$zip" "$member" | jq -r '.version // empty'; done | sort -u)
fi
if [[ ! $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "::error::${zip}: expected one release version, found '${version}'"
  exit 1
fi

tag="v${version}"
asset=$(basename "$zip")
sha=$(sha256sum "$zip" | cut -d' ' -f1)
line="- Upload \`${asset}\` at ${where}. SHA-256: \`${sha}\`"
summary=${GITHUB_STEP_SUMMARY:-/dev/stdout}

if ! gh release view "$tag" >/dev/null 2>&1; then
  notes="Plugin packages for the Senzing MCP server v${version}.

${line}"
  gh release create "$tag" "$zip" --target "$target" --title "$tag" --notes "$notes"
  echo "Created release ${tag} with ${asset} (sha256 ${sha})." >> "$summary"
  exit 0
fi

assets=$(gh release view "$tag" --json assets -q '.assets[].name')
if ! grep -qxF "$asset" <<<"$assets"; then
  gh release upload "$tag" "$zip"
  body=$(gh release view "$tag" --json body -q .body)
  gh release edit "$tag" --notes "${body}

${line}"
  echo "Added ${asset} to release ${tag} (sha256 ${sha})." >> "$summary"
  exit 0
fi

previous=$(mktemp -d)
trap 'rm -rf "$previous"' EXIT
gh release download "$tag" --pattern "$asset" --dir "$previous"
if cmp -s "$zip" "$previous/$asset"; then
  echo "Release ${tag} already has this ${asset}; nothing to do." >> "$summary"
  exit 0
fi

msg="Release ${tag} has a ${asset} that differs from main. A package update needs a new version number, so this change ships with the next version bump."
echo "::warning::${msg}"
echo "${msg}" >> "$summary"
