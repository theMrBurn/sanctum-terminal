.PHONY: install test status clean

install:
	/opt/homebrew/bin/python3.12 -m pip install -e . --break-system-packages

test:
	export PYTHONPATH=.:src && /opt/homebrew/bin/python3.12 -m pytest -vs tests/

status:
	sanctum status portland

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf *.egg-info .pytest_cache

	# Run a scouting mission in the current city
scout:
	sanctum scout portland