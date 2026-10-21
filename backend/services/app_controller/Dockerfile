# The App Controller (Phase 14 WS6 6.8): the backend image plus kopf.
#   docker build -f services/app_controller/Dockerfile --build-arg BASE=<registry>/hb-api:<tag> .
ARG BASE=hb-api:local
FROM ${BASE}
USER root
COPY services/app_controller/requirements.txt /tmp/app-controller-requirements.txt
RUN pip install --no-cache-dir -r /tmp/app-controller-requirements.txt
COPY services/app_controller /app/services/app_controller
# kopf loads main.py by its path, so /app (the backend's src) must be on the path itself.
ENV PYTHONPATH=/app
USER 10001
CMD ["kopf", "run", "--all-namespaces", "--standalone", "--liveness=http://0.0.0.0:8080/healthz", "/app/services/app_controller/main.py"]
