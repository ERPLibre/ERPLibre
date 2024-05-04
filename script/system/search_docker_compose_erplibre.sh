#!/bin/bash

USE_LOCATE=true

if [ "$USE_LOCATE" == false ]
then
  find "/" -name "docker-compose.yml" -type f -print 2>/dev/null | grep -v .repo | grep -v /var/lib/docker | xargs -I {} sh -c 'grep -l "ERPLibre" "{}" 2>/dev/null || true'
#  SEARCH_PATH="/"
#  find "$SEARCH_PATH" -name "docker-compose.yml" -type f 2>/dev/null | grep -v .repo | while read -r file; do
#      grep -q "ERPLibre" "$file" && echo "$file"
#  done
elif [ "$USE_LOCATE" == true ]
then
  locate -b -r "^docker-compose\.yml$" | grep -v .repo | grep -v /var/lib/docker | xargs -I {} sh -c "grep -l \"ERPLibre\" \"{}\" 2>/dev/null || true"
#  locate -b -r '^docker-compose\.yml$' | grep -v .repo | while read -r file; do
#    if [ -f "$file" ]; then
#      grep -q 'ERPLibre' "$file" && echo "$file"
#    fi
#  done
fi
