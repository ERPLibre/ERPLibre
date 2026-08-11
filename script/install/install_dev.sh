#!/usr/bin/env bash

if [[ "${OSTYPE}" == "linux-gnu" ]]; then
  source /etc/os-release
  if [[ "${ID}" == "ubuntu" ]]; then
    # 20.04 et 22.04 retirees : leur chaine d'outils ne suffit plus a ERPLibre
    # (pikepdf exige qpdf >= 12.2, en C++20, quand focal livre GCC 9). Les
    # versions intermediaires EOL (22.10, 23.04, 23.10, 25.04) partent avec.
    if [[ "${VERSION_ID}" == "24.04" || "${VERSION_ID}" == "25.10" || "${VERSION_ID}" == "26.04" ]]; then
      echo "\n---- linux-gnu installation process started ----"
      ./script/install/install_debian_dependency.sh
    else
      echo "Your version is not supported, only support 24.04, 25.10, 26.04 : ${VERSION_ID}"
      exit 1
    fi
  elif [[ "${ID}" == "linuxmint" ]]; then
    if [[ "${VERSION_ID}" == "22.3" ]]; then
      echo "\n---- linux-gnu installation process started ----"
      ./script/install/install_debian_dependency.sh
    else
      echo "Your version is not supported, only support 22.3 : ${VERSION_ID}"
    fi
  elif [[ "${ID}" == "debian" ]]; then
    ./script/install/install_debian_dependency.sh
  elif [[ "${ID}" == "arch" ]]; then
    ./script/install/install_arch_linux.sh
  elif [[ "${ID}" == "fedora" || "${ID_LIKE}" == *"fedora"* || "${ID_LIKE}" == *"rhel"* ]]; then
    # AlmaLinux et Rocky declarent ID_LIKE="rhel centos fedora" : elles passent
    # donc par ce meme script, qui aiguille dnf.
    echo "\n---- Fedora/RHEL installation process started ----"
    ./script/install/install_fedora_dependency.sh
  else
    ./script/install/install_debian_dependency.sh
    echo "Your Linux system is not supported, only support Ubuntu 24.04, 25.10, 26.04, Linux Mint 22.3, Debian, Fedora, AlmaLinux, Rocky Linux, Arch."
  fi
elif [[ "${OSTYPE}" == "darwin"* ]]; then
  echo "\n---- Darwin installation process started ----"
  ./script/install/install_OSX_dependency.sh
fi
