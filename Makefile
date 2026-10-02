.PHONY: setup up down restart logs test backup restore update

setup:
	./setup.sh

up:
	docker compose up -d --build

down:
	docker compose down

restart:
	docker compose restart logger

logs:
	docker compose logs -f --tail=100 logger

test:
	python3 -m unittest discover -s tests -v

backup:
	./scripts/backup.sh

restore:
	./scripts/restore.sh "$(BACKUP)"

update:
	./scripts/update.sh
