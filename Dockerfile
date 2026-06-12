# CAREX - Build reproductible des tuiles DVF
# docker build -t dvf-tiles .
# docker run --rm -v $(pwd)/data:/app/data -v $(pwd)/build:/app/build dvf-tiles france
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libsqlite3-dev zlib1g-dev git ca-certificates curl \
      python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# tippecanoe (felt), version figee
ARG TIPPECANOE_REF=2.78.0
RUN git clone --depth 1 --branch ${TIPPECANOE_REF} https://github.com/felt/tippecanoe.git /tmp/tippecanoe \
    && make -C /tmp/tippecanoe -j"$(nproc)" \
    && make -C /tmp/tippecanoe install \
    && rm -rf /tmp/tippecanoe

RUN pip3 install --break-system-packages --no-cache-dir \
      duckdb mapbox-vector-tile pmtiles

WORKDIR /app
COPY pipeline/ pipeline/
RUN chmod +x pipeline/*.sh

# data/ et build/ sont des volumes (cache CSV + artefact en sortie)
ENTRYPOINT ["./pipeline/run_pipeline.sh"]
CMD ["poc"]
