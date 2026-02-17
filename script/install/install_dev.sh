#!/usr/bin/env bash

if [[ "${OSTYPE}" == "linux-gnu" ]]; then
  source /etc/os-release
  if [[ "${ID}" == "ubuntu" ]]; then
    if [[ "${VERSION_ID}" == "18.04" || "${VERSION_ID}" == "20.04" || "${VERSION_ID}" == "22.04" || "${VERSION_ID}" == "22.10" || "${VERSION_ID}" == "23.04" || "${VERSION_ID}" == "23.10" || "${VERSION_ID}" == "24.04" || "${VERSION_ID}" == "25.04" || "${VERSION_ID}" == "25.10" ]]; then
      echo "\n---- linux-gnu installation process started ----"
      ./script/install/install_debian_dependency.sh
    else
      echo "Your version is not supported, only support 18.04, 20.04 and 22.04 - 24.04, 25.04, 25.10 : ${VERSION_ID}"
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
  else
    ./script/install/install_debian_dependency.sh
    echo "Your Linux system is not supported, only support Ubuntu 18.04 or Ubuntu 20.04 or Ubuntu 22.04 - Ubuntu 23.10 - Ubuntu 24.04, Ubuntu 25.04, Ubuntu 25.10 ."
  fi
elif [[ "${OSTYPE}" == "darwin"* ]]; then
  echo "\n---- Darwin installation process started ----"
  ./script/install/install_OSX_dependency.sh
fi
