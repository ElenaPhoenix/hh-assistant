FROM python:3.10-slim

# Устанавливаем Node.js для работы hh-applicant-tool
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Устанавливаем hh-applicant-tool
RUN npm install -g hh-applicant-tool

WORKDIR /app

# Копируем зависимости и ставим их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код проекта
COPY . .

# Запускаем главное меню
CMD ["python", "main.py"]