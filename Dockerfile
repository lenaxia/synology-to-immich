FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY schema/ schema/
RUN pip install --no-cache-dir -e .

COPY config.example.yaml config.yaml

CMD ["syno-bridge"]
