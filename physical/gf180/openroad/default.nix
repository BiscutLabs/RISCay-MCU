# Pinned diagnostic/runtime candidate; does not change the default mapper.
let
  pkgs = import (builtins.fetchTarball {
    url = "https://releases.nixos.org/nixpkgs/nixpkgs-26.11pre1093421.f20cd90e28fe/nixexprs.tar.zst";
    sha256 = "sha256-MTJCMrhDFb+GRbLxBPTp8kB4dDlO+egmQ5qsJgYuaWw=";
  }) {};
in pkgs.openroad.overrideAttrs (old: {
  patches = old.patches ++ [ ./repair-progress.patch ];
})
