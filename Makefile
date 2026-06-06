.PHONY: up run ps results preview down reset

up:
	docker compose up -d --build

run:
	python3 -u scripts/run_experiment.py

ps:
	docker compose ps

results:
	python3 -m json.tool results/latest-run.json

preview:
	cd article && python3 -m http.server 8788 --bind 127.0.0.1

down:
	docker compose down

reset:
	docker compose down --volumes --remove-orphans
