# format everything
fmt:
	docker-compose run --rm web isort .
	docker-compose run --rm web black .

# check formatting without modifying files
check-fmt:
	docker-compose run --rm web isort . --check-only
	docker-compose run --rm web black . --check

# run functional tests in the development image against PostgreSQL
.PHONY: test
test:
	docker compose up -d --wait postgresql
	docker compose run --build --rm --no-deps -T --entrypoint python web -m pytest -q \
		--postgresql-host=postgresql --postgresql-port=5432 --postgresql-user=admin --postgresql-password=root

# launch the application in docker-compose
.PHONY: pypistats
pypistats:
	docker-compose down
	docker-compose build
	docker-compose up

# bring down the application and destroy the db volumes
cleanup:
	docker-compose down -v

# setup a local environment
setup:
	brew install asdf || true
	asdf install
	pip install -r requirements-dev.txt

# update requirements files
.PHONY: update-deps
update-deps:
	pip-compile --upgrade --generate-hashes --resolver=backtracking requirements.in -o requirements.txt
	pip-compile --upgrade --allow-unsafe --generate-hashes --resolver=backtracking requirements-dev.in -o requirements-dev.txt


# port forward flower
pfflower:
	open http://localhost:7777 && kubectl get pods -n pypistats | grep flower | awk '{print $$1}' | xargs -I % kubectl port-forward -n pypistats % 7777:5555

# port forward web
pfweb:
	open http://localhost:7000 && kubectl get pods -n pypistats | grep web | awk '{print $$1}' | xargs -I % kubectl port-forward -n pypistats % 7000:5000
