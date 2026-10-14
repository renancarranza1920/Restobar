#!/usr/bin/env bash
# Run on Oracle. Default --check is read-only; --apply requires a full commit.
set -euo pipefail
umask 077
source_dir=/home/ubuntu/proyectos/restobar-preview
deploy_dir=/home/ubuntu/proyectos/restobar-deploy
project=restobar-preview
mode=${1:---check}
release=${2:-}
if [[ "$mode" != --check && "$mode" != --apply ]]; then
  echo 'Uso: bash deploy/update-preview.sh --check | --apply COMMIT_COMPLETO' >&2; exit 1
fi
cd "$source_dir"
app_id=$(docker ps -q --filter label=com.docker.compose.project="$project" --filter label=com.docker.compose.service=app)
db_id=$(docker ps -q --filter label=com.docker.compose.project="$project" --filter label=com.docker.compose.service=db)
[[ -n "$app_id" && "$app_id" != *$'\n'* && -n "$db_id" && "$db_id" != *$'\n'* ]] || { echo 'Debe existir un app y un db activos de restobar-preview.' >&2; exit 1; }
config_files=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$app_id")
IFS=',' read -r -a files <<< "$config_files"
base=(docker compose --project-directory "$deploy_dir" -p "$project")
for file in "${files[@]}"; do
  if [[ "$file" == "$source_dir/deploy/preview.override.yml" ]]; then continue; fi
  [[ "$file" == "$deploy_dir/"* && -f "$file" ]] || { echo 'Compose fuera de restobar-deploy. Revisa la ruta antes de continuar.' >&2; exit 1; }
  base+=(-f "$file")
done
"${base[@]}" config --quiet
python3 - "$app_id" "$db_id" "$source_dir" <<'PY'
import json, subprocess, sys
app, db = json.loads(subprocess.check_output(['docker','inspect',sys.argv[1],sys.argv[2]]))
for container in (app, db):
    assert container['Config']['Labels']['com.docker.compose.project']=='restobar-preview'
    for mount in container['Mounts']:
        if mount['Type']=='volume':
            assert mount['Name'].startswith('restobar-preview_'), 'Volumen compartido con otro proyecto'
        else:
            assert mount['Type']=='bind' and mount['Source'].startswith('/home/ubuntu/proyectos/restobar-'), 'Montaje externo inesperado'
            assert not mount['Source'].startswith(sys.argv[3]), 'El código está montado en vivo; este procedimiento requiere una imagen'
ports=app['NetworkSettings']['Ports'].get('8000/tcp',[])
assert ports and all(p['HostIp']=='127.0.0.1' and p['HostPort']=='8004' for p in ports), 'Puerto inesperado'
env=dict(v.split('=',1) for v in app['Config']['Env'] if '=' in v)
assert env.get('DTE_TRANSMISSION_ENABLED','0').lower() not in {'1','true','yes','on'}, 'Hacienda está habilitada'
assert any(m['Destination']=='/var/lib/mysql' and m['Type']=='volume' for m in db['Mounts']), 'Falta el volumen MySQL persistente'
print('Verificado: proyecto exclusivo, volúmenes propios, 127.0.0.1:8004 y Hacienda desactivada.')
PY
if [[ "$mode" == --check ]]; then
  echo 'Preparado. --apply construye app, respalda MySQL/archivos y comprueba que el historial anterior permanezca idéntico.'
  exit 0
fi
[[ "$release" =~ ^[0-9a-f]{40}$ ]] || { echo 'Indica el SHA completo publicado y verificado.' >&2; exit 1; }
[[ -z $(git status --porcelain) ]] || { echo 'Hay cambios locales. Consérvalos y revisa antes de actualizar.' >&2; exit 1; }
git fetch origin rework/restobar-fast-service
[[ $(git rev-parse FETCH_HEAD) == "$release" ]] || { echo 'El commit no coincide con la rama publicada.' >&2; exit 1; }
git merge-base --is-ancestor 56a64533eb12ad9c34152d4a0907ae2552e74799 "$release"
previous_commit=$(git rev-parse HEAD)
old_image=$(docker inspect --format '{{.Image}}' "$app_id")
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="$deploy_dir/backups/$stamp-${release:0:12}"
mkdir -p "$backup"
chmod 700 "$deploy_dir/backups" "$backup"
printf '%s\n' "$previous_commit" > "$backup/previous-commit.txt"
printf '%s\n' "$release" > "$backup/release-commit.txt"
printf '%s\n' "$config_files" > "$backup/compose-files.txt"
[[ ! -f "$deploy_dir/.env" ]] || cp -p "$deploy_dir/.env" "$backup/config.env.private"
for file in "${files[@]}"; do cp -p "$file" "$backup/$(basename "$file").original"; done
docker image tag "$old_image" "restobar-preview-app:rollback-$stamp"
cat > "$backup/rollback.yml" <<YAML
services:
  app:
    image: restobar-preview-app:rollback-$stamp
    environment:
      DTE_TRANSMISSION_ENABLED: "0"
      DTE_ENVIRONMENT: "00"
YAML
other_state() {
  python3 - <<'PY'
import json, subprocess
ids=subprocess.check_output(['docker','ps','-q']).decode().split()
containers=json.loads(subprocess.check_output(['docker','inspect',*ids])) if ids else []
print(json.dumps(sorted((c['Id'],c['State']['StartedAt']) for c in containers
    if c['Config'].get('Labels',{}).get('com.docker.compose.project')!='restobar-preview')))
PY
}
other_state > "$backup/other-containers.before.json"
paused=0
finished=0
recover() {
  result=$?
  if (( result != 0 && paused && ! finished )); then
    echo 'La comprobación falló. Recuperando únicamente la imagen anterior de app.' >&2
    "${base[@]}" -f "$backup/rollback.yml" up -d --no-deps --no-build app || true
    echo "Respaldo privado: $backup. La base no se restaura automáticamente ni se borran volúmenes." >&2
  fi
  exit "$result"
}
trap recover EXIT
git switch --detach "$release"
export RESTOBAR_RELEASE="$release"
candidate=("${base[@]}" -f "$source_dir/deploy/preview.override.yml")
"${candidate[@]}" config --quiet
# Build while the previous app still serves traffic. No db recreation or prune.
"${candidate[@]}" build app
"${base[@]}" stop app
paused=1
docker exec "$db_id" sh -ec 'test -n "$MYSQL_ROOT_PASSWORD"; test -n "$MYSQL_DATABASE"; export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysqldump -uroot --single-transaction --routines --events --triggers --hex-blob --set-gtid-purged=OFF --no-tablespaces --databases "$MYSQL_DATABASE"' | gzip > "$backup/database.sql.gz"
gzip -t "$backup/database.sql.gz"
docker cp "$app_id:/app/app/static/uploads/products" "$backup/products"
docker cp "$app_id:/app/app/static/uploads/branding" "$backup/branding"
docker cp "$app_id:/app/instance" "$backup/instance"
"${base[@]}" -f "$backup/rollback.yml" run --rm --no-deps -T app python - < "$source_dir/deploy/database_fingerprint.py" > "$backup/database.before.json"
"${candidate[@]}" run --rm --no-deps -T app python - --initialize < "$source_dir/deploy/database_fingerprint.py" > "$backup/database.after.json"
python3 - "$backup/database.before.json" "$backup/database.after.json" <<'PY'
import json,sys
before,after=(json.load(open(p)) for p in sys.argv[1:])
changed=[name for name, fingerprint in before['tables'].items() if after['tables'].get(name)!=fingerprint]
assert not changed, 'Cambió el contenido anterior de: '+', '.join(changed)
assert after['dte_transmission_enabled'] is False
print('Datos previos, documentos fiscales, firmas, respuestas y auditoría conservados exactamente.')
PY
"${candidate[@]}" up -d --no-deps --no-build --wait --wait-timeout 120 app
curl --fail --silent --show-error http://127.0.0.1:8004/api/health
other_state > "$backup/other-containers.after.json"
cmp "$backup/other-containers.before.json" "$backup/other-containers.after.json"
finished=1
echo
echo "Actualizado únicamente restobar-preview/app. Respaldo: $backup"
echo 'Caddy y los demás contenedores permanecen sin cambios.'
