#!/usr/bin/env bash
# This host's OAI lab only. Preserve subscriber secrets/SQN; discard runtime contexts.
set -Eeuo pipefail

lab_base=/home/mohit/jinkun
core_file="$lab_base/oai-cn5g/docker-compose.yaml"
ran_dir="$lab_base/openairinterface5g"
build_dir="$ran_dir/cmake_targets/ran_build/build"
gnb_config="$ran_dir/targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb.sa.band78.fr1.106PRB.usrpx310.redcap.yaml"
unit=oai-redcap-gnb.service
nic=ens7f0
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
compose=(docker compose --project-name oai-cn5g --file "$core_file")
services=(mysql ims oai-nrf oai-udr oai-udm oai-ausf oai-amf oai-smf oai-upf oai-ext-dn)
runtime_services=(ims oai-nrf oai-udr oai-udm oai-ausf oai-amf oai-smf oai-upf oai-ext-dn)

log() { printf '[%(%H:%M:%S)T] %s\n' -1 "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }
usage() {
    echo "Usage: sudo bash $0 {check|stop|start --ue-off}"
    echo 'start clears runtime registration/session records, but NEVER subscriber credentials/SQN.'
    echo 'Power OFF the UE and stop its connection watcher before using start --ue-off.'
}

[[ ${1:-} == --help || ${1:-} == -h ]] && { usage; exit 0; }
[[ $EUID == 0 ]] || die 'Run with sudo.'
action=${1:-}
case "$action" in
    check|stop) [[ $# == 1 ]] || { usage; exit 2; } ;;
    start) [[ $# == 2 && $2 == --ue-off ]] || { usage; exit 2; } ;;
    *) usage; exit 2 ;;
esac
for tool in docker systemctl systemd-run journalctl ip sysctl flock pgrep; do
    command -v "$tool" >/dev/null || die "Missing command: $tool"
done
[[ -f $core_file ]] || die "Missing $core_file"
docker info >/dev/null
"${compose[@]}" config --quiet

# Fail closed if the project scope has changed since this script was written.
expected=$(printf '%s\n' "${services[@]}" | sort)
actual=$("${compose[@]}" config --services | sort)
[[ $actual == "$expected" ]] || die 'Unexpected Compose service set; review the script before proceeding.'
for service in "${services[@]}"; do
    project=$(docker inspect "$service" --format '{{index .Config.Labels "com.docker.compose.project"}}')
    [[ $project == oai-cn5g ]] || die "Container $service is not owned by the lab project."
done

stop_lab() {
    if [[ $(systemctl show "$unit" -p LoadState --value) != not-found ]]; then
        systemctl stop "$unit"
    fi
    "${compose[@]}" stop --timeout 30 "${services[@]}"
    [[ -z $("${compose[@]}" ps --status running -q) ]] || die 'Some lab containers remain running.'
    if pgrep -x nr-softmodem >/dev/null; then
        die 'A separate nr-softmodem is running. Not killing an unowned process; stop it manually.'
    fi
    log 'gNB and all ten lab containers are stopped.'
}

if [[ $action == stop ]]; then
    install -d -m 700 /run/oai-network-fresh
    exec 9>/run/oai-network-fresh/lock
    flock -n 9 || die 'Another network-fresh instance is running.'
    stop_lab
    exit 0
fi

for file in "$build_dir/nr-softmodem" "$gnb_config" "$script_dir/tune-x310.sh" \
    "$lab_base/oai-cn5g/conf/config.yaml" "$lab_base/oai-cn5g/database/oai_db.sql" \
    "$lab_base/oai-cn5g/healthscripts/mysql-healthcheck.sh" \
    "$lab_base/oai-cn5g/conf/sip.conf" "$lab_base/oai-cn5g/conf/users.conf"; do
    [[ -f $file ]] || die "Missing file: $file"
done
[[ -x $build_dir/nr-softmodem ]] || die 'nr-softmodem is not executable.'
command -v ethtool >/dev/null || die 'Missing ethtool.'
ip -4 addr show dev "$nic" | grep -q 'inet 192.168.40.1/24' || die 'X310 NIC address is not 192.168.40.1/24.'
db_volume=$(docker inspect mysql --format '{{range .Mounts}}{{if eq .Destination "/var/lib/mysql"}}{{.Name}}{{end}}{{end}}')
[[ -n $db_volume ]] || die 'No existing MySQL data volume; refusing to initialize from an old SQL snapshot.'
docker volume inspect "$db_volume" >/dev/null
while IFS= read -r image; do
    docker image inspect "$image" >/dev/null || die "Required local image missing: $image"
done < <("${compose[@]}" config --images)
log 'Preflight passed: project scope, local images, files, NIC, and existing MySQL volume.'
if [[ $action == check ]]; then
    log 'Read-only check complete. RF operation and startup are not tested.'
    exit 0
fi

install -d -m 700 /run/oai-network-fresh
exec 9>/run/oai-network-fresh/lock
flock -n 9 || die 'Another network-fresh instance is running.'

cleanup_failure() {
    local result=$?
    trap - EXIT
    if (( result != 0 )); then
        log 'Startup failed; stopping the lab. Inspect journalctl/docker logs for the cause.'
        systemctl stop "$unit" 2>/dev/null || true
        "${compose[@]}" stop --timeout 30 "${services[@]}" || true
    fi
    exit "$result"
}
trap cleanup_failure EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wait_healthy() {
    local deadline=$((SECONDS + 180)) service status ready
    while (( SECONDS < deadline )); do
        ready=yes
        for service in "$@"; do
            status=$(docker inspect "$service" --format '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}missing-healthcheck{{end}}')
            case "$status" in
                running/healthy) ;;
                running/starting) ready=no ;;
                *) die "$service is $status; see docker logs $service" ;;
            esac
        done
        [[ $ready == yes ]] && return 0
        sleep 3
    done
    die 'Core health checks did not finish within 180 seconds.'
}

stop_lab
log 'Recreating MySQL, retaining its current subscriber/authentication data volume.'
# Never use down -v, --renew-anon-volumes, or import an older subscriber snapshot.
"${compose[@]}" up -d --no-deps --force-recreate --no-build --pull never mysql
new_db_volume=$(docker inspect mysql --format '{{range .Mounts}}{{if eq .Destination "/var/lib/mysql"}}{{.Name}}{{end}}{{end}}')
[[ $new_db_volume == "$db_volume" ]] || die 'MySQL volume identity changed unexpectedly.'
wait_healthy mysql

log 'Clearing runtime AMF registrations, SMF registrations, SDM subscriptions and authentication status.'
# Other core functions are stopped: no concurrent writes. All four tables use InnoDB.
# The SQL below NEVER updates AuthenticationSubscription (K/OPc/SQN) or provisioning tables.
docker exec -i mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --user=root --database=oai_db --batch' <<'SQL'
START TRANSACTION;
DELETE FROM Amf3GppAccessRegistration;
DELETE FROM SmfRegistrations;
DELETE FROM SdmSubscriptions;
DELETE FROM AuthenticationStatus;
COMMIT;
SELECT 'remaining runtime rows' AS check_name,
  (SELECT COUNT(*) FROM Amf3GppAccessRegistration) +
  (SELECT COUNT(*) FROM SmfRegistrations) +
  (SELECT COUNT(*) FROM SdmSubscriptions) +
  (SELECT COUNT(*) FROM AuthenticationStatus) AS row_count;
SQL

log 'Recreating the nine remaining core containers with fresh process/network-namespace state.'
"${compose[@]}" up -d --no-deps --force-recreate --no-build --pull never "${runtime_services[@]}"
wait_healthy "${services[@]}"
log 'All ten core containers are healthy. Tuning the dedicated X310 NIC.'
bash "$script_dir/tune-x310.sh" "$nic"
sysctl -w net.ipv4.ip_forward=1
systemctl reset-failed "$unit" 2>/dev/null || true
systemd-run --unit="$unit" --description='OAI RedCap gNB (fresh X310 run)' \
    --property="WorkingDirectory=$build_dir" --property=Restart=no \
    --setenv="LD_LIBRARY_PATH=$build_dir" \
    "$build_dir/nr-softmodem" -O "$gnb_config" \
    '--gNBs.[0].min_rxtxtime' 6 --usrp-tx-thread-config 1 -E --continuous-tx
invocation=$(systemctl show "$unit" -p InvocationID --value)
[[ -n $invocation ]] || die 'Missing gNB invocation ID.'
deadline=$((SECONDS + 90))
while (( SECONDS < deadline )); do
    systemctl is-active --quiet "$unit" || die 'gNB exited during startup.'
    startup_log=$(journalctl "_SYSTEMD_INVOCATION_ID=$invocation" --no-pager -o cat)
    if [[ $startup_log == *'Received NGSetupResponse from AMF'* && $startup_log == *'RU 0 RF started'* ]]; then
        # UHD can lower these during radio initialization.
        sysctl -w net.core.wmem_max=62500000 net.core.rmem_max=62500000
        log 'NETWORK READY: all core containers healthy, NG Setup accepted, RF-start marker seen.'
        log 'Now power on the UE and run the laptop connection helper. No UE registration is implied yet.'
        exit 0
    fi
    sleep 2
done
die 'No NG Setup/RF-start confirmation within 90 seconds.'
