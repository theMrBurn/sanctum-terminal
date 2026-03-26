clean:
	rm -rf data/live_assets/*
	find . -type d -name "__pycache__" -exec rm -rf {} +

factory:
	python3 utils/VoxelFactory.py

test:
	PYTHONPATH=. ./.venv/bin/python -m pytest tests/

run:
	python3 SimulationRunner.py