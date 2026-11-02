# kayaAI kum havuzu (Adım 19c): ajanların yazdığı Python kodu yalnız bu imajdan oluşan, ağsız, salt-okunur,
# yetkisiz ve kaynak sınırlı konteynerde çalışır. Kurmak (internet gerekir, bir kez): kayaai sandbox build
FROM python:3.12-slim

RUN pip install --no-cache-dir "pandas==2.2.*" "numpy==2.*" "matplotlib==3.9.*" "openpyxl==3.1.*" \
 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin runner \
 && rm -rf /root/.cache

COPY run.sh /opt/kayaai/run.sh
RUN chmod 0555 /opt/kayaai/run.sh

USER 10001:10001
WORKDIR /in
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg HOME=/tmp MPLCONFIGDIR=/tmp
ENTRYPOINT ["/opt/kayaai/run.sh"]
