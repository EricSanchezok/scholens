#!/bin/sh
set -eu
umask 077
: "${CACHE_API_PASSWORD:?API cache credential is required}"
: "${CACHE_JOBS_PASSWORD:?Jobs cache credential is required}"
api_hash=$(printf '%s' "$CACHE_API_PASSWORD" | sha256sum | cut -d ' ' -f1)
jobs_hash=$(printf '%s' "$CACHE_JOBS_PASSWORD" | sha256sum | cut -d ' ' -f1)
printf 'user default off\nuser scholens-api on #%s ~scholens:rate:* ~scholens:concurrency:* ~scholens:translation:* ~scholens:conversation-events:* +@all -@dangerous\nuser scholens-jobs on #%s ~scholens:pdf-parse:* +@all -@dangerous\n' "$api_hash" "$jobs_hash" > /tmp/users.acl
unset CACHE_API_PASSWORD CACHE_JOBS_PASSWORD
exec valkey-server /etc/valkey/valkey.conf --aclfile /tmp/users.acl
