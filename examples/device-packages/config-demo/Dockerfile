FROM alpine:3.22
# No experiment interfaces are created in this image. The platform supplies veth.
RUN mkdir -p /etc/route-ovs-demo /usr/local/bin \
    && printf '%s\n' 'message=initial-configuration' > /etc/route-ovs-demo/startup.conf \
    && printf '%s\n' '#!/bin/sh' 'set -eu' \
       'mkdir -p /run/route-ovs-demo' \
       'cp /etc/route-ovs-demo/startup.conf /run/route-ovs-demo/running.conf' \
       'exec sleep infinity' > /usr/local/bin/route-ovs-demo-start \
    && chmod 0755 /usr/local/bin/route-ovs-demo-start
CMD ["/usr/local/bin/route-ovs-demo-start"]
