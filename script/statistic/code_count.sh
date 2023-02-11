#!/usr/bin/env bash
# all argument is directory/file separate by space

./.venv/bin/pygount --duplicates --folders-to-skip="[...],*/libs/*,*/lib/*,lib" --names-to-skip="[...],*.min.*" --suffix=py,xml,html,js,css,scss --format=summary "$@"
