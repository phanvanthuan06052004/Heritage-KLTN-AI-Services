import os
import sys
import paramiko

SERVER = "180.93.43.7"
PORT = 22
USER = "root"
PASSWORD = "@Sieutoc!dVCvasYDzZS"
REMOTE_DIR = "/heritage-stag/AI-CHATBOX"
COMPOSE_FILE = "docker-compose.yml"
SERVICE = "heritage_ai_api"

LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))

SYNC_ITEMS = {
    "files": ["docker-compose.yml", "Dockerfile", "entrypoint.sh", "pyproject.toml", "alembic.ini", ".env.docker"],
    "dirs": ["app", "alembic", "skills", "frontend"],
}

EXCLUDE_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules", ".pytest_cache", ".ruff_cache", ".claude",
                "docs", "temp_uploads", ".gitattributes", ".vite", "__MACOSX", ".storybook"}
EXCLUDE_EXTENSIONS = {".pyc", ".pyo", ".log"}


class Deployer:
    def __init__(self):
        self.client = None
        self.sftp = None

    def connect(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(SERVER, PORT, USER, PASSWORD, timeout=60)
        self.sftp = self.client.open_sftp()
        print("  Connected.")

    def close(self):
        if self.sftp:
            self.sftp.close()
        if self.client:
            self.client.close()

    def run(self, cmd, desc="", quiet=False):
        if desc:
            print(f"  [{desc}]")
        if not quiet:
            print(f"  $ {cmd}")
        stdin, stdout, stderr = self.client.exec_command(cmd)
        out = stdout.read().decode()
        err = stderr.read().decode()
        if out.strip() and not quiet:
            print(out.strip())
        if err.strip():
            print(f"  ! {err.strip()}")
        return out, err

    def mkdir_p(self, path):
        self.run(f"mkdir -p '{path}'", quiet=True)

    def upload_file(self, local_path, remote_path):
        print(f"  Uploading: {os.path.basename(local_path)}")
        self.sftp.put(local_path, remote_path)

    def upload_dir(self, local_dir, remote_base):
        self.mkdir_p(remote_base)
        for root, dirs, files in os.walk(local_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for d in dirs:
                rp = os.path.join(remote_base, os.path.relpath(os.path.join(root, d), local_dir)).replace("\\", "/")
                self.mkdir_p(rp)
            for f in files:
                _, ext = os.path.splitext(f)
                if ext in EXCLUDE_EXTENSIONS:
                    continue
                lp = os.path.join(root, f)
                rel = os.path.relpath(lp, local_dir)
                rp = os.path.join(remote_base, rel).replace("\\", "/")
                print(f"  Uploading: {rel}")
                self.sftp.put(lp, rp)


def sync():
    d = Deployer()
    try:
        d.connect()
        print("\n[sync] Creating remote directory...")
        d.run(f"mkdir -p {REMOTE_DIR}")

        print("[sync] Uploading files...")
        for f in SYNC_ITEMS["files"]:
            local_f = os.path.join(LOCAL_DIR, f)
            if os.path.exists(local_f):
                d.upload_file(local_f, f"{REMOTE_DIR}/{f}")
            else:
                print(f"  WARNING: {f} not found, skipping")

        for dname in SYNC_ITEMS["dirs"]:
            local_d = os.path.join(LOCAL_DIR, dname)
            if os.path.isdir(local_d):
                d.upload_dir(local_d, f"{REMOTE_DIR}/{dname}")
            else:
                print(f"  WARNING: {dname}/ not found, skipping")

        print("  Sync done.")
        print("\n[sync] Linking .env.docker -> .env for docker-compose variable substitution...")
        d.run(f"cd {REMOTE_DIR} && cp .env.docker .env")
    finally:
        d.close()


def build():
    d = Deployer()
    try:
        d.connect()
        print("\n[build] Building Docker images on server...")
        d.run(f"cd {REMOTE_DIR} && docker compose -f {COMPOSE_FILE} build")
    finally:
        d.close()


def up():
    d = Deployer()
    try:
        d.connect()
        print(f"\n[up] Starting {SERVICE}...")
        d.run(f"cd {REMOTE_DIR} && docker compose -f {COMPOSE_FILE} up -d")
        print(f"  API:      http://{SERVER}:5055")
        print(f"  Frontend: http://{SERVER}:3119")
    finally:
        d.close()


def down():
    d = Deployer()
    try:
        d.connect()
        print(f"\n[down] Stopping {SERVICE} (data preserved)...")
        d.run(f"cd {REMOTE_DIR} && docker compose -f {COMPOSE_FILE} down")
    finally:
        d.close()


def restart():
    d = Deployer()
    try:
        d.connect()
        print(f"\n[restart] Restarting {SERVICE}...")
        d.run(f"cd {REMOTE_DIR} && docker compose -f {COMPOSE_FILE} down")
        d.run(f"cd {REMOTE_DIR} && docker compose -f {COMPOSE_FILE} up -d")
    finally:
        d.close()


def deploy():
    sync()
    build()
    up()
    print(f"\n=== DEPLOY DONE ===")
    print(f"  API:      http://{SERVER}:5055")
    print(f"  Frontend: http://{SERVER}:3119")


def logs():
    d = Deployer()
    try:
        d.connect()
        d.run(f"cd {REMOTE_DIR} && docker compose -f {COMPOSE_FILE} logs -f --tail=100")
    finally:
        d.close()


def logs_api():
    d = Deployer()
    try:
        d.connect()
        d.run(f"cd {REMOTE_DIR} && docker compose -f {COMPOSE_FILE} logs -f --tail=100 api")
    finally:
        d.close()


def logs_worker():
    d = Deployer()
    try:
        d.connect()
        d.run(f"cd {REMOTE_DIR} && docker compose -f {COMPOSE_FILE} logs -f --tail=100 worker")
    finally:
        d.close()


def status():
    d = Deployer()
    try:
        d.connect()
        d.run(f"cd {REMOTE_DIR} && docker compose -f {COMPOSE_FILE} ps")
    finally:
        d.close()


def ssh():
    d = Deployer()
    try:
        d.connect()
        print(f"\n=== SSH to {SERVER} ===")
        d.run("bash -i", desc="Starting interactive shell")
    finally:
        d.close()


ACTIONS = {
    "sync": sync,
    "build": build,
    "up": up,
    "down": down,
    "restart": restart,
    "deploy": deploy,
    "logs": logs,
    "logs-api": logs_api,
    "logs-worker": logs_worker,
    "status": status,
    "ssh": ssh,
}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python deploy.py <action>")
        print(f"Actions: {', '.join(ACTIONS.keys())}")
        sys.exit(1)

    action = sys.argv[1]
    if action in ACTIONS:
        ACTIONS[action]()
    else:
        print(f"Unknown action: {action}")
        print(f"Available: {', '.join(ACTIONS.keys())}")
        sys.exit(1)
