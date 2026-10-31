#!/usr/bin/env bash
# Downloads pinned repository-check tools into .tools/ and verifies each checksum.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tools="$root/.tools"
mkdir -p "$tools"

case "$(uname -s)" in
  Linux) platform=linux ;;
  MINGW* | MSYS* | CYGWIN*) platform=windows ;;
  *)
    echo "Unsupported platform: $(uname -s)" >&2
    exit 1
    ;;
esac

install() {
  local name="$1" url="$2" sha256="$3" binary="$4"
  local archive
  archive="$tools/$(basename "$url")"

  if [[ -x "$tools/$name" || -x "$tools/$name.exe" ]]; then
    return
  fi

  curl --fail --silent --show-error --location --output "$archive" "$url"
  echo "$sha256  $archive" | sha256sum --check --quiet

  local unpacked
  unpacked="$(mktemp -d)"
  case "$archive" in
    *.zip) powershell.exe -NoProfile -Command \
      "Expand-Archive -LiteralPath '$(cygpath -w "$archive")' -DestinationPath '$(cygpath -w "$unpacked")'" ;;
    *) tar --extract --gzip --file "$archive" --directory "$unpacked" ;;
  esac

  local suffix=""
  [[ "$platform" == windows ]] && suffix=".exe"
  mv "$unpacked/$binary$suffix" "$tools/$name$suffix"
  rm -rf "$unpacked" "$archive"
}

gitleaks=https://github.com/gitleaks/gitleaks/releases/download/v8.30.1
actionlint=https://github.com/rhysd/actionlint/releases/download/v1.7.12
ec=https://github.com/editorconfig-checker/editorconfig-checker/releases/download/v4.0.2

if [[ "$platform" == linux ]]; then
  install gitleaks "$gitleaks/gitleaks_8.30.1_linux_x64.tar.gz" \
    551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb gitleaks
  install actionlint "$actionlint/actionlint_1.7.12_linux_amd64.tar.gz" \
    8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8 actionlint
  install ec "$ec/editorconfig-checker-linux-amd64.tar.gz" \
    44efaef3ed14c6ab52eb87481d78e5e5c204796dccf26e2f4598a61ba17f8003 editorconfig-checker
else
  install gitleaks "$gitleaks/gitleaks_8.30.1_windows_x64.zip" \
    d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e gitleaks
  install actionlint "$actionlint/actionlint_1.7.12_windows_amd64.zip" \
    6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9 actionlint
  install ec "$ec/editorconfig-checker-windows-amd64.tar.gz" \
    c3fe98bc10fc3a6f0470f5a364dffbf53861633a0108bd15123cecc66d41bf00 editorconfig-checker
fi
