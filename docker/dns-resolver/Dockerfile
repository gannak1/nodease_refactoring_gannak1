FROM alpine:3.21.3

RUN apk add --no-cache dnsmasq

COPY docker/dns-resolver/dnsmasq-https.conf /etc/dnsmasq-https.conf
COPY docker/dns-resolver/dnsmasq-http.conf /etc/dnsmasq-http.conf

ENTRYPOINT ["dnsmasq"]