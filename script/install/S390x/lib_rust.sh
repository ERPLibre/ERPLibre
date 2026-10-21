#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque SOURÇABLE : une chaîne Rust assez récente pour ce qu'on compile.
#
# Réservé aux architectures sans roue PyPI par l'appelant : ailleurs pip pose
# des binaires et rien ne se compile. Le seuil est celui du paquet Rust le
# plus exigeant : orjson 3.13 (verrou d'Odoo 18) déclare rust-version 1.95,
# et maturin refuse tout rustc plus ancien ; cryptography, lui, s'arrête sous
# 1.78 sur son Cargo.lock v4. Le seuil ne dépend pas de la distribution, d'où
# une seule bibliothèque pour apt, dnf et zypper.

EL_RUST_MIN_MINOR="${EL_RUST_MIN_MINOR:-95}"

# Vrai si le cargo du PATH atteint 1.${EL_RUST_MIN_MINOR}. /usr/local/bin en
# tête : c'est là que el_rust_ensure expose la chaîne de rustup.
el_cargo_assez_recent() {
  local ver major rest minor
  ver="$(PATH=/usr/local/bin:$PATH cargo --version 2> /dev/null | awk '{print $2}')"
  major="${ver%%.*}"
  rest="${ver#*.}"
  minor="${rest%%.*}"
  [[ "${major}" =~ ^[0-9]+$ && "${minor}" =~ ^[0-9]+$ ]] || return 1
  [[ ${major} -gt 1 ]] || [[ ${major} -eq 1 && ${minor} -ge ${EL_RUST_MIN_MINOR} ]]
}

# Complète par rustup quand la distribution livre un Rust trop ancien.
#
# La chaîne est exposée dans /usr/local/bin, hors du shell de connexion : les
# étapes suivantes sont des processus distincts, qui ne liront ni ~/.bashrc
# ni ~/.cargo/env. Ne s'arrête jamais : les versions d'Odoo dont le verrou n'a
# pas orjson 3.13 s'en passent, et un arrêt les priverait d'installation.
el_rust_ensure() {
  el_cargo_assez_recent && return 0
  echo "cargo trop ancien ($(cargo --version 2> /dev/null || echo absent)), 1.${EL_RUST_MIN_MINOR} requis : installation via rustup."
  # Le Rust de la distribution reste installé : rustup le signale par
  # « error: cannot install while Rust is installed », puis passe outre
  # sous -y. RUSTUP_INIT_SKIP_PATH_CHECK lui fait sauter ce contrôle, et le
  # journal ne porte plus une erreur qui n'en est pas une.
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | RUSTUP_INIT_SKIP_PATH_CHECK=yes \
      sh -s -- -y --profile minimal --default-toolchain stable
  for bin in cargo rustc; do
    if [ -x "${HOME}/.cargo/bin/${bin}" ]; then
      sudo ln -sf "${HOME}/.cargo/bin/${bin}" "/usr/local/bin/${bin}"
    fi
  done
  echo "cargo retenu : $(PATH=/usr/local/bin:$PATH cargo --version 2> /dev/null || echo absent)"
  # rustup injoignable (proxy, miroir hors ligne) laisse le cargo de la
  # distribution en place sans un mot : l'échec ne se verrait qu'au build
  # d'orjson, au fond de la sortie de poetry. On le nomme ici.
  if ! el_cargo_assez_recent; then
    echo "AVERTISSEMENT : cargo reste sous 1.${EL_RUST_MIN_MINOR}, rustup a echoue."
    echo "  L'installation d'Odoo 18 s'arretera sur orjson. Rejouez quand"
    echo "  https://sh.rustup.rs est joignable : make install_os"
  fi
  return 0
}
