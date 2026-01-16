#!/bin/sh
set -eu

python manage.py migrate --noinput

if [ "${SKIP_COLLECTSTATIC:-0}" != "1" ]; then
  python manage.py collectstatic --noinput
fi

exec "$@"
