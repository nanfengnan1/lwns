# This two-file example wraps an existing, locally prepared FRR base image.
# Use a tested digest instead of a floating tag for a reproducible release.
FROM alpine/frr:latest
RUN mkdir -p /etc/frr \
    && touch /etc/frr/frr.conf /etc/frr/vtysh.conf \
    && chown -R frr:frr /etc/frr
CMD ["/usr/lib/frr/docker-start"]
