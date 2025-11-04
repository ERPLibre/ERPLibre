#!/usr/bin/env bash
# test_performance.sh https://website.com

#ulimit -n 200000

# (facultatif mais utile) sysctl temporaires pour la machine de test :
#sudo sysctl -w net.core.somaxconn=65535
#sudo sysctl -w net.core.netdev_max_backlog=250000
#sudo sysctl -w net.ipv4.ip_local_port_range="1024 65000"
#sudo sysctl -w net.ipv4.tcp_fin_timeout=15

for c in 25 50 100 200 400; do
  echo "== Concurrency: $c =="
  #oha -z 30s -c $c $1 | tee -a results.txt
  wrk -t$(nproc) -c$c -d30s "$1" | tee -a results.txt
done
