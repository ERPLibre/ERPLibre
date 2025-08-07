#!/usr/bin/env bash
cmd1="find \"$*\" -type f -not -path \"*/not_supported_files/*\" -name '*.py' -print0 | parallel -0 ./script/maintenance/format_python.sh {}"
cmd2="find \"$*\" -type f -not -path \"*/not_supported_files/*\" -name '*.xml' -print0 | parallel -0 ./script/maintenance/prettier_xml.sh {}"
cmd3="find \"$*\" -type f -not -path \"*/not_supported_files/*\" -name '*.js' -print0 | parallel -0 ./script/maintenance/prettier.sh {}"
cmd4="find \"$*\" -type f -not -path \"*/not_supported_files/*\" -name '*.css' -print0 | parallel -0 ./script/maintenance/prettier.sh {}"
cmd5="find \"$*\" -type f -not -path \"*/not_supported_files/*\" -name '*.scss' -print0 | parallel -0 ./script/maintenance/prettier.sh {}"
cmd6="find \"$*\" -type f -not -path \"*/not_supported_files/*\" -name '*.html' -print0 | parallel -0 ./script/maintenance/prettier.sh {}"
cmd7="find \"$*\" -type f -not -path \"*/not_supported_files/*\" -name '*.sh' -print0 | parallel -0 ./script/maintenance/format_bash.sh {}"
parallel ::: "$cmd1" "$cmd2" "$cmd3" "$cmd4" "$cmd5" "$cmd6" "$cmd7"
