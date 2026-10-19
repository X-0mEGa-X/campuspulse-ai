FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY campuspulse ./campuspulse
COPY .streamlit/config.toml ./.streamlit/config.toml
COPY app.py .
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "streamlit run app.py --server.address 0.0.0.0 --server.port ${PORT}"]
