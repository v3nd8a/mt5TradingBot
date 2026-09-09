FROM python:3.12-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем проект
COPY . .

# Создаём директории
RUN mkdir -p logs tests

# Команда по умолчанию
CMD ["python", "-m", "main"]
