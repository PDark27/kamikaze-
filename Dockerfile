# Fiscaliza — imagem de produção do app web (PWA)
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
COPY config/ config/
COPY webapp/ webapp/

RUN pip install --no-cache-dir . fastapi "uvicorn[standard]"

ENV PORT=8000
ENV FISCALIZA_PARAMETROS=/app/config/parametros_risco.yaml
EXPOSE 8000

# --proxy-headers para HTTPS atrás do balanceador da hospedagem
CMD uvicorn webapp.app:app --host 0.0.0.0 --port ${PORT} --proxy-headers
