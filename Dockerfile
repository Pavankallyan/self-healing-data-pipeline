FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Generate the demo data, then run the pipeline for both days.
CMD ["sh", "-c", "python src/generate_data.py && python run_pipeline.py --day day1 && python run_pipeline.py --day day2"]
