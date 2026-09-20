SHELL := /bin/bash
VENV := .venv
PY := $(VENV)/bin/python
CONFIG ?= debug

.PHONY: help setup build bundle test monitor synthetic doctor record viz asana capture poses clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | expand -t22

setup: ## create the venv and install the python package (editable) + dev deps
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e "python[viz,dev]"

build: ## compile the swift capture tool
	cd swift-capture && swift build $(if $(filter release,$(CONFIG)),-c release,)

bundle: build ## wrap the binary in a .app so macOS can grant motion permission
	CONFIG=$(CONFIG) ./scripts/make_app_bundle.sh

test: ## run the python test suite (no hardware needed)
	cd python && ../$(PY) -m pytest -q

doctor: bundle ## check the live capture path end to end
	$(VENV)/bin/airpod-pose doctor

monitor: ## live pose readout from the AirPods
	$(VENV)/bin/airpod-pose monitor

synthetic: ## same readout, fake data, no hardware
	$(VENV)/bin/airpod-pose monitor --source synthetic

viz: ## live 3D plot from the AirPods
	$(VENV)/bin/airpod-pose viz

capture: ## capture the pose you are holding: make capture NAME=triangle_right LABEL="Triangle (right)"
	$(VENV)/bin/airpod-pose asana --capture $(NAME) $(if $(LABEL),--label "$(LABEL)",) $(if $(HOLD),--hold $(HOLD),)

asana: ## live held-pose coach against the captured library
	$(VENV)/bin/airpod-pose asana

poses: ## list the captured pose library
	$(VENV)/bin/airpod-pose asana --list

record: ## record a session: make record OUT=data/nod-01.jsonl
	$(VENV)/bin/airpod-pose record --out $(or $(OUT),data/session.jsonl)

clean:
	rm -rf build swift-capture/.build python/*.egg-info .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
