.PHONY: build run gateway docker-build docker-run doctor test compile

build:
	python -m pip install -e .

run:
	python -m shaka.cli run

gateway:
	python -m shaka.cli gateway

docker-build:
	docker build -t shaka-agent .

docker-run:
	docker run --rm -it -p 18789:18789 -e SHAKA_PROVIDER=groq -e SHAKA_API_KEY=changeme -e SHAKA_GATEWAY_TOKEN=change-me shaka-agent

doctor:
	python -m shaka.cli doctor

test:
	python -m pytest -q tests

compile:
	python -m compileall shaka
