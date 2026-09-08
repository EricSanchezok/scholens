#!/usr/bin/env bash
# Sign a Valkey leaf with the existing Account Center private CA; never replace the CA.
set -euo pipefail
mountpoint -q /srv/sanchezcloud
ca_dir=/srv/sanchezcloud/pki
tls_dir=/srv/sanchezcloud/valkey-tls
test -s "$ca_dir/ca.key"
openssl x509 -in "$ca_dir/ca.crt" -checkend 2592000 -noout
install -d -m 0700 "$tls_dir"
install -d -m 0755 /srv/sanchezcloud/valkey /srv/sanchezcloud/valkey-config
chown 999:999 /srv/sanchezcloud/valkey
umask 077
if [[ ! -e "$tls_dir/server.key" && ! -e "$tls_dir/server.crt" ]]; then
  openssl req -new -newkey rsa:3072 -nodes \
    -subj '/CN=cache.personal.svc.sanchezcloud' \
    -keyout "$tls_dir/server.key" -out "$ca_dir/valkey.csr" 2>/dev/null
  cat > "$ca_dir/valkey.ext" <<'EXT'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:cache.personal.svc.sanchezcloud,IP:10.84.1.10
EXT
  openssl x509 -req -sha256 -days 365 -in "$ca_dir/valkey.csr" \
    -CA "$ca_dir/ca.crt" -CAkey "$ca_dir/ca.key" -CAcreateserial \
    -extfile "$ca_dir/valkey.ext" -out "$tls_dir/server.crt" 2>/dev/null
  rm "$ca_dir/valkey.csr"
fi
test -s "$tls_dir/server.key"
openssl verify -CAfile "$ca_dir/ca.crt" -verify_hostname cache.personal.svc.sanchezcloud "$tls_dir/server.crt"
openssl x509 -in "$tls_dir/server.crt" -checkend 2592000 -noout
chmod 0600 "$tls_dir/server.key"
chmod 0644 "$tls_dir/server.crt"
chown -R 999:999 "$tls_dir"
