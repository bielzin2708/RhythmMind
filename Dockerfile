FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RHYTHMMIND_AMBIENTE=producao \
    PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd --create-home --shell /usr/sbin/nologin appuser

COPY api ./api
COPY core ./core
COPY static ./static
COPY main.py ./main.py
COPY data/base_conhecimento.json ./data/base_conhecimento.json
COPY data/catalogo_referencia.json ./data/catalogo_referencia.json
COPY data/dicionario_emocional.json ./data/dicionario_emocional.json

USER appuser

EXPOSE 8080

CMD ["python", "-m", "api.producao"]
