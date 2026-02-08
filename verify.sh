#!/bin/bash
set -e

dummy() {
  echo >/dev/null
}

exefile=$1
#verfile=$exefile.expect
verfile=$2

exec 3<$verfile

lineno=1

./$exefile | while true; do
  read exeline
  read verline <&3
  if [ "$exeline" == "$verline" ]; then
    printf "%s  [OK]\n" "$exeline"
  else
    echo "    At line $lineno [FAIL]"
    printf "    Result:   '%s'\n" "$exeline"
    printf "    Expected: '%s'\n" "$verline"
  fi
  dummy $((lineno += 1))
done
