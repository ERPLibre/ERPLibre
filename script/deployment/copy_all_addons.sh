#!/bin/bash
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

datetime=$(date +%Y-%m-%d_%H-%M-%S)
backup_dir="backup_$datetime"
mkdir -p "$backup_dir"

for dir in */; do
  if [ -d "$dir/addons/addons" ]; then
    mkdir -p "$backup_dir/$dir"

    # Support when addons is a symlink, copy the target directory
    if [ -L "$dir/addons/addons" ]; then
      source_dir=$(readlink -f "$dir/addons/addons")
    else
      source_dir="$dir/addons/addons"
    fi

    echo $source_dir

    # Copy directory of addons
    cp -r "$source_dir" "$backup_dir/$dir/addons"

    # Copy docker-compose.yml
    cp "$dir/docker-compose.yml" "$backup_dir/$dir/"
  fi
done
