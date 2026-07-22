FROM ubuntu/squid:6.6-24.04_edge@sha256:8a3baed477e2c282ab8aa5edad442f69873246964f225c5c2ae8364b6610963c

USER root
COPY --chown=13:13 docker/proxy/squid.conf /etc/squid/squid.conf
COPY --chown=13:13 docker/proxy/authorized-sources.conf /etc/squid/authorized-sources.conf

USER 13:13
EXPOSE 3128 3129

ENTRYPOINT ["squid"]
CMD ["-NYC", "-f", "/etc/squid/squid.conf"]
