.PHONY: sync build up down restart deploy logs logs-api logs-worker status

sync:
	python deploy.py sync

build:
	python deploy.py build

up:
	python deploy.py up

down:
	python deploy.py down

restart:
	python deploy.py restart

deploy:
	python deploy.py deploy

logs:
	python deploy.py logs

logs-api:
	python deploy.py logs-api

logs-worker:
	python deploy.py logs-worker

status:
	python deploy.py status
