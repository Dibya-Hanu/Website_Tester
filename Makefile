.PHONY: up labs down test frontend sample
up:
	docker compose up --build -d
labs:
	docker compose --profile labs up --build -d
down:
	docker compose --profile labs down
test:
	cd backend && ../.venv/bin/pytest -q
frontend:
	cd frontend && npm ci && npm run build
sample:
	python scripts/generate_sample.py --url http://juice-shop:3000/
