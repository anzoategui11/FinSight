FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /frontend
COPY frontend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY frontend/app.py ./app.py
RUN useradd -m -u 10002 streamlit
USER streamlit
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
