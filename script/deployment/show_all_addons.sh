#!/bin/bash
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

for dir in */; do
  if [ -d "$dir/addons/addons" ]; then
    echo "Directory : $dir"

    find "$dir/addons/addons" -type f -print
  fi
done
