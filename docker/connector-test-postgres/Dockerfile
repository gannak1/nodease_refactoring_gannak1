FROM pgvector/pgvector:pg15

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*

COPY docker/connector-test-postgres/generate-certificates.sh \
    /usr/local/bin/generate-connector-test-certificates

RUN chmod 0755 /usr/local/bin/generate-connector-test-certificates
