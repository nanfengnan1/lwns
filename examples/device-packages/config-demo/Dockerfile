FROM alpine:3.22
# No experiment interfaces are created in this image. The platform supplies veth.
RUN mkdir -p /etc/lwns-demo /usr/local/bin \
    && printf '%s\n' 'message=initial-configuration' > /etc/lwns-demo/startup.conf \
    && printf '%s\n' '#!/bin/sh' 'set -eu' \
       'mkdir -p /run/lwns-demo' \
       'cp /etc/lwns-demo/startup.conf /run/lwns-demo/running.conf' \
       'exec sleep infinity' > /usr/local/bin/lwns-demo-start \
    && chmod 0755 /usr/local/bin/lwns-demo-start
CMD ["/usr/local/bin/lwns-demo-start"]
