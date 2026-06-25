.PHONY: up down logs cli test obs build-multiarch

up:            ## start the full stack
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f app

cli:           ## run the sample case end-to-end (no UI)
	docker compose run --rm app ama run --case data/sample_case --yes

obs:           ## start with Phoenix observability overlay
	docker compose -f docker-compose.yml -f observability/compose.phoenix.yml up --build

test:          ## offline tests (no GPU / no servers needed)
	python3 -m pytest tests/ -q

build-multiarch:  ## build + push multi-arch images (set REGISTRY)
	docker buildx build --platform linux/amd64,linux/arm64 -t $(REGISTRY)/ama-app:0.1.0 --push .
	docker buildx build --platform linux/amd64,linux/arm64 -t $(REGISTRY)/ama-serving:0.1.0 --push serving
	docker buildx build --platform linux/amd64,linux/arm64 -t $(REGISTRY)/ama-ui:0.1.0 --push ui
