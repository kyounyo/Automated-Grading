# Running AutoGrade+ with Docker

This is the easiest way to run AutoGrade+ on any computer (Windows, macOS or Linux).
You don't need Python, Node.js or a database installed. Docker handles all of it.

## What you need

1. **Docker Desktop**: download it from https://www.docker.com/products/docker-desktop/ and start it
   (on Linux, install Docker Engine with the Compose plugin).
2. **An OpenRouter API key**: create one at https://openrouter.ai/keys. Grading calls are billed to this key.
3. **This project folder**: download the ZIP from GitHub, or run
   `git clone https://github.com/kyounyo/Automated-Grading.git`

## First-time setup

Open a terminal **inside the project folder** (PowerShell on Windows, Terminal on macOS) and run:

**macOS / Linux**
```bash
cp .env.example .env
```

**Windows (PowerShell)**
```powershell
copy .env.example .env
```

Open the new `.env` file in any text editor and replace `your_openrouter_api_key_here` with your key.

## Start the app

```bash
docker compose up -d --build
```

The first build downloads everything and takes about 5–10 minutes. After that, the app starts in a few seconds.

Then open **http://localhost:8080** in your browser.

| What              | Where                      |
|-------------------|----------------------------|
| AutoGrade+ app    | http://localhost:8080      |
| API documentation | http://localhost:8080/docs |

## Everyday commands

| Task                                | Command                                          |
|-------------------------------------|--------------------------------------------------|
| Start                               | `docker compose up -d`                           |
| Stop                                | `docker compose down`                            |
| See logs (grading progress, errors) | `docker compose logs -f backend`                 |
| Check status                        | `docker compose ps`                              |
| Update after pulling new code       | `docker compose up -d --build`                   |
| Wipe all assignments and grades     | `docker compose exec backend python reset_db.py` |

## Where is my data?

Assignments, grades, the vector store and uploaded files are stored in three Docker volumes:
`autograde_data`, `autograde_chroma` and `autograde_uploads`. They are kept when you stop,
restart or rebuild the app.

> ⚠️ `docker compose down -v` (with `-v`) **permanently deletes** all of that data.

**Back up the database**
```bash
docker compose cp backend:/app/data/autograde.db ./autograde-backup.db
```

## Changing settings

Edit `.env`, then run `docker compose up -d` again.

- **Port**: if 8080 is already in use, set `APP_PORT=9090` (or any free port) and open that port instead.
- **Model**: change `LLM_MODEL` / `AUDITOR_MODEL` to any OpenRouter model ID.

## Troubleshooting

- **`Missing OPENROUTER_API_KEY`**: you haven't created `.env`, or the key line is empty. See *First-time setup*.
- **`port is already allocated`**: another program is using the port. Change `APP_PORT` in `.env`.
- **Page loads but grading fails**: check `docker compose logs backend`. Usually the API key is wrong or out of credit.
- **`Cannot connect to the Docker daemon`**: Docker Desktop isn't running. Start it and try again.

## Security note

The app has no login. Anyone who can reach port 8080 on this computer can see student
submissions and start grading on your API key. That's fine on a personal computer, but
don't open the port to the internet or a shared network without adding authentication
in front of it.
