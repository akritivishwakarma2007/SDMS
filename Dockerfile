FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sdms ./sdms
ENV SDMS_DATA=/data
CMD ["uvicorn", "sdms.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
