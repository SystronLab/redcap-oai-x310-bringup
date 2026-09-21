#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
sql_file=${1:-"$repo_dir/config/subscriber-001010000134378.sql"}
mysql_container=${MYSQL_CONTAINER:-mysql}

if [[ ! -f "$sql_file" ]]; then
  printf 'Subscriber SQL file not found: %s\n' "$sql_file" >&2
  printf 'Pass the provisioning SQL path as argument 1.\n' >&2
  exit 1
fi

docker inspect "$mysql_container" >/dev/null
docker exec -i "$mysql_container" sh -c \
  'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' <"$sql_file"

docker exec "$mysql_container" sh -c \
  'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" --batch --raw \
    -e "SELECT a.ueid, a.authenticationMethod, a.authenticationManagementField,
               a.algorithmId, s.servingPlmnid, s.singleNssai
        FROM AuthenticationSubscription a
        JOIN SessionManagementSubscriptionData s ON s.ueid=a.ueid
        WHERE a.ueid=\"001010000134378\";"'
