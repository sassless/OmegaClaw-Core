# Omega 2.0 development image built from commit
# 6e9f0fbb944b64d15a4ee5b668be874619d9378a.
# Pin the multi-platform manifest digest so rebuilds use the same base image.
FROM singularitynet/omega@sha256:2bf10b939b8280e57f7a8e81cc766df90ed22c455f945eb8de099284f67f3bce

COPY requirements.txt /tmp/asi-omega-plugin-requirements.txt
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-pip \
 && python3 -m pip install --no-cache-dir --break-system-packages \
      -r /tmp/asi-omega-plugin-requirements.txt \
 && rm -rf /var/lib/apt/lists/*
