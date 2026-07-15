#!/bin/sh
set -eu

ca_dir="${CONNECTOR_TEST_CA_PRIVATE_DIR:-/tls/ca-private}"
server_dir="${CONNECTOR_TEST_SERVER_TLS_DIR:-/tls/server}"
public_dir="${CONNECTOR_TEST_PUBLIC_CA_DIR:-/tls/public}"

umask 077
mkdir -p "$ca_dir" "$server_dir" "$public_dir"

ca_is_valid=false
if [ -f "$ca_dir/ca.key" ] && [ -f "$ca_dir/ca.crt" ]; then
    if openssl x509 -checkend 86400 -noout -in "$ca_dir/ca.crt" \
        >/dev/null 2>&1; then
        ca_is_valid=true
    fi
fi

if [ "$ca_is_valid" != true ]; then
    ca_work_dir="$(mktemp -d "$ca_dir/.generate.XXXXXX")"
    trap 'rm -rf "${ca_work_dir:-}" "${server_work_dir:-}"' EXIT
    openssl genpkey -algorithm RSA \
        -pkeyopt rsa_keygen_bits:3072 \
        -out "$ca_work_dir/ca.key" >/dev/null 2>&1
    openssl req -x509 -new -sha256 -days 30 \
        -key "$ca_work_dir/ca.key" \
        -subj "/CN=Nodease Local Connector Test CA" \
        -out "$ca_work_dir/ca.crt" >/dev/null 2>&1
    chmod 0600 "$ca_work_dir/ca.key"
    chmod 0644 "$ca_work_dir/ca.crt"
    mv -f "$ca_work_dir/ca.key" "$ca_dir/ca.key"
    mv -f "$ca_work_dir/ca.crt" "$ca_dir/ca.crt"
    rmdir "$ca_work_dir"
    ca_is_valid=true
fi

server_is_valid=false
if [ -f "$server_dir/server.key" ] && [ -f "$server_dir/server.crt" ]; then
    if openssl x509 -checkend 86400 -noout -in "$server_dir/server.crt" \
        >/dev/null 2>&1 \
        && openssl verify -CAfile "$ca_dir/ca.crt" \
            -verify_hostname connector-test-postgres \
            "$server_dir/server.crt" >/dev/null 2>&1 \
        && openssl verify -CAfile "$ca_dir/ca.crt" \
            -verify_hostname localhost \
            "$server_dir/server.crt" >/dev/null 2>&1; then
        server_is_valid=true
    fi
fi

if [ "$server_is_valid" != true ]; then
    server_work_dir="$(mktemp -d "$server_dir/.generate.XXXXXX")"
    trap 'rm -rf "${ca_work_dir:-}" "${server_work_dir:-}"' EXIT
    openssl genpkey -algorithm RSA \
        -pkeyopt rsa_keygen_bits:3072 \
        -out "$server_work_dir/server.key" >/dev/null 2>&1
    openssl req -new -sha256 \
        -key "$server_work_dir/server.key" \
        -subj "/CN=connector-test-postgres" \
        -out "$server_work_dir/server.csr" >/dev/null 2>&1
    cat > "$server_work_dir/server.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:connector-test-postgres,DNS:localhost
EOF
    openssl x509 -req -sha256 -days 14 \
        -in "$server_work_dir/server.csr" \
        -CA "$ca_dir/ca.crt" \
        -CAkey "$ca_dir/ca.key" \
        -CAcreateserial \
        -extfile "$server_work_dir/server.ext" \
        -out "$server_work_dir/server.crt" >/dev/null 2>&1
    chmod 0600 "$server_work_dir/server.key"
    chmod 0644 "$server_work_dir/server.crt"
    chown postgres:postgres \
        "$server_work_dir/server.key" \
        "$server_work_dir/server.crt"
    mv -f "$server_work_dir/server.key" "$server_dir/server.key"
    mv -f "$server_work_dir/server.crt" "$server_dir/server.crt"
    rm -f "$server_work_dir/server.csr" "$server_work_dir/server.ext"
    rmdir "$server_work_dir"
fi

if [ ! -s "$server_dir/demo-password" ]; then
    password_file="$(mktemp "$server_dir/.password.XXXXXX")"
    openssl rand -base64 48 | tr -d '\r\n' > "$password_file"
    chmod 0600 "$password_file"
    chown postgres:postgres "$password_file"
    mv -f "$password_file" "$server_dir/demo-password"
fi

public_ca_file="$(mktemp "$public_dir/.ca.XXXXXX")"
cp "$ca_dir/ca.crt" "$public_ca_file"
chmod 0644 "$public_ca_file"
mv -f "$public_ca_file" "$public_dir/ca.crt"

trap - EXIT
