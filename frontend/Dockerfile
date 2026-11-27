FROM python:3.12-slim

WORKDIR /ui
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY requirements-calendar.txt .
RUN pip install --no-cache-dir -r requirements-calendar.txt
COPY app.py calendar_view.py ./
COPY .streamlit/ ./.streamlit/
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.headless=true"]
