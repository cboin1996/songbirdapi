# songbirdapi 🐦

Music downloading REST api featuring mp3 or m4a tagging.

# Installation

TODO: document this section with install instructions.

## Debug API

Vscode debugger can be configured to the run `server.py` file
with the following `.vscode/launch.json` configuration:

```json
{
	"configurations": [
		{
			"name": "Songbird: API",
			"type": "python",
			"request": "launch",
			"module": "uvicorn",
			"args": ["songbirdapi.server:app", "--reload", "--log-level", "debug"],
			"jinja": true,
			"justMyCode": true,
			"envFile": "./dev.env"
		},
	]
},
```

## Linting

To lint the app, run

```
make lint
```

## Configuration

The following table summarizes the configurable parameters for the app,
these can be setup in a `.env` file at the root of the project,
and passed to docker with `--env-file .env`.

| Variable  | Type | Default | Description                                                                |
| --------- | ---- | ------- | -------------------------------------------------------------------------- |
| RUN_LOCAL | bool | False   | Whether to run the app locally, or configure it for running in a container |