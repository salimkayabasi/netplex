import asyncio
import os
import uvicorn
from src.database import init_db
from src.scheduler import start_scheduler
from src.web.app import app, download_and_cache_tudum_css, ensure_config_www_mounted
from src.logger import get_logger

logger = get_logger("netplex.main")

async def run_server(host: str, port: int):
    config = uvicorn.Config(app=app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    db_path = os.environ.get("NETPLEX_DB_PATH", "/config/netplex.db")
    config_dir = os.environ.get("NETPLEX_CONFIG_DIR", "/config")
    host = os.environ.get("NETPLEX_HOST", "0.0.0.0")
    port = int(os.environ.get("NETPLEX_PORT", "8000"))

    logger.info("Initializing NetPlex application...")
    
    # Initialize SQLite database schema
    init_db(db_path)
    app.state.db_path = db_path
    
    # Ensure /config/www directory is set up and mounted
    ensure_config_www_mounted(config_dir)

    # Download and cache initial Tudum CSS stylesheet
    try:
        download_and_cache_tudum_css(config_dir)
        logger.info("Initial Tudum CSS cached successfully.")
    except Exception as e:
        logger.warning(f"Initial Tudum CSS caching encountered an issue: {e}")

    # Launch daemon scheduler in background thread and web server concurrently
    scheduler_task = asyncio.create_task(asyncio.to_thread(start_scheduler, db_path))
    server_task = asyncio.create_task(run_server(host, port))

    await asyncio.gather(server_task, scheduler_task)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("NetPlex shutting down.")
